import hashlib
import json
from datetime import datetime, timezone

import pytest

import commitments
import db
from models import GroundReading, Prediction


def _pred(ts="2026-01-01T00:00:00+00:00", pm=12.3, station="bloomsbury"):
    return Prediction(
        station_id=station, timestamp=datetime.fromisoformat(ts),
        predicted_pm25=pm, confidence=0.7, strategy_version="v1-baseline",
        agent_version="aeroloop-0.1", inputs={"pm25_model": pm},
        source_timestamps={"x": ts},
    )


def test_canonical_hash_deterministic_and_rehashes(temp_db):
    pid = db.save_prediction(_pred(), kind="live")
    row = db.get_prediction(pid)
    payload = json.loads(row["commit_payload"])
    # canonical: sorted keys, no spaces — re-serialising gives the same string
    assert json.dumps(payload, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False) == row["commit_payload"]
    assert hashlib.sha256(row["commit_payload"].encode()).hexdigest() == row["commit_hash"]
    assert payload["kind"] == "live"
    assert payload["v"] == 1


def test_kind_and_recorded_at(temp_db):
    from datetime import timezone as tz
    pid = db.save_prediction(_pred(), kind="hindcast")
    db.save_reading(GroundReading(
        station_id="bloomsbury", timestamp=datetime(2026, 1, 1, tzinfo=tz.utc),
        measured_pm25=11.0, source="LAQN test"))
    row = db.get_prediction(pid)
    assert row["commit_kind"] == "hindcast"
    reading = db.get_reading("bloomsbury", "2026-01-01T00:00:00+00:00")
    assert reading["recorded_at"]


@pytest.mark.parametrize("n", [1, 2, 3, 5, 8])
def test_merkle_root_proof_and_tamper(n):
    hashes = [hashlib.sha256(f"h{i}".encode()).hexdigest() for i in range(n)]
    root = commitments.merkle_root(hashes)
    for i in range(n):
        proof = commitments.merkle_proof(hashes, i)
        assert commitments.verify_proof(hashes[i], proof, root)
    # tampered leaf fails
    bad = hashlib.sha256(b"bad").hexdigest()
    assert not commitments.verify_proof(bad, commitments.merkle_proof(hashes, 0), root)
    # wrong index fails
    if n > 1:
        assert not commitments.verify_proof(
            hashes[1], commitments.merkle_proof(hashes, 0), root)


def test_merkle_domain_separation():
    # a leaf over h must differ from an internal node over (h, h)
    h = hashlib.sha256(b"x").hexdigest()
    leaf = commitments._leaf(h)
    node = commitments._node(bytes.fromhex(h), bytes.fromhex(h))
    assert leaf != node
    # single-leaf root equals the leaf hash, not the raw commit hash
    assert commitments.merkle_root([h]) == leaf.hex() != h


def _seed_predictions(temp_db, n=4):
    ids = []
    for i in range(n):
        ids.append(db.save_prediction(_pred(pm=10.0 + i), kind="simulated"))
    return ids[0] if n == 1 else ids


def test_build_batch_filters_and_idempotent(temp_db, monkeypatch, tmp_path):
    monkeypatch.setenv("ANCHORS_DIR", str(tmp_path / "anchors"))
    _seed_predictions(temp_db)
    today = datetime.now(timezone.utc).date().isoformat()

    # refuses today without force
    r = commitments.build_batch(today)
    assert r["status"] == "error"
    assert "not finished" in r["error"]

    a = commitments.build_batch(today, force=True)
    assert a["status"] == "built"
    assert a["n_leaves"] == 4
    assert len(a["root"]) == 64
    # anchor_id stamped on leaves; public record written
    assert (tmp_path / "anchors" / f"{today}.json").exists()
    assert all(db.get_prediction(i + 1)["anchor_id"] == a["id"] for i in range(4))

    # idempotent: second build returns the existing anchor
    again = commitments.build_batch(today, force=True)
    assert again["status"] == "exists"
    assert again["id"] == a["id"]

    # a date with no commits is a no-op
    empty = commitments.build_batch("2020-01-01")
    assert empty["status"] == "empty"


def test_prediction_commitment_view(temp_db, monkeypatch, tmp_path):
    monkeypatch.setenv("ANCHORS_DIR", str(tmp_path / "anchors"))
    pid = db.save_prediction(_pred(), kind="simulated")
    view = commitments.prediction_commitment(pid)
    assert view["hash_matches"] is True
    assert view["kind"] == "simulated"
    assert view["reading"] is None
    assert view["anchor"] is None

    # tamper the stored payload -> hash no longer matches
    c = db._conn()
    c.execute("UPDATE predictions SET commit_payload=? WHERE id=?",
              (view["commit_payload"].replace("12.3", "99.9"), pid))
    c.commit()
    c.close()
    assert commitments.prediction_commitment(pid)["hash_matches"] is False


def test_reading_recorded_after_commit(temp_db):
    pid = db.save_prediction(_pred(), kind="live")
    db.save_reading(GroundReading(
        station_id="bloomsbury",
        timestamp=datetime(2026, 1, 1, tzinfo=timezone.utc),
        measured_pm25=11.0, source="LAQN test"))
    view = commitments.prediction_commitment(pid)
    assert view["reading"]["measured_pm25"] == 11.0
    assert view["reading_recorded_after_commit"] is True
    assert "self-reported" in view["committed_at_note"]


def test_existed_by_from_confirmed_base(temp_db, monkeypatch, tmp_path):
    """Once Base confirms, block time is the public 'existed by' bound."""
    monkeypatch.setenv("ANCHORS_DIR", str(tmp_path / "anchors"))
    pid = _seed_predictions(temp_db, 1)
    today = datetime.now(timezone.utc).date().isoformat()
    commitments.build_batch(today, force=True)
    anchor = db.get_anchor_by_date(today)
    db.update_anchor(
        anchor["id"], base_status="confirmed", base_network="base-sepolia",
        base_block_time="2025-12-31T00:00:00Z")
    view = commitments.prediction_commitment(pid)
    assert view["existed_by"] == "2025-12-31T00:00:00Z"
    assert view["existed_by_source"] == "base-sepolia"
    # prediction target (2026-01-01) is after the anchor time -> provably forecast
    assert view["target_after_existed_by"] is True


def test_anchor_root_tamper_breaks_consistency(temp_db, monkeypatch, tmp_path):
    """Tampering the DB anchor root must be caught against the published file."""
    monkeypatch.setenv("ANCHORS_DIR", str(tmp_path / "anchors"))
    pid = _seed_predictions(temp_db, 1)
    today = datetime.now(timezone.utc).date().isoformat()
    commitments.build_batch(today, force=True)
    anchor = db.get_anchor_by_date(today)
    db.update_anchor(anchor["id"], root="ff" * 32)
    view = commitments.prediction_commitment(pid)
    assert view["anchor"]["roots_consistent"] is False
    assert view["anchor"]["proof_valid"] is False
    assert view["anchor"]["published_root"] != view["anchor"]["root"]


def test_missing_published_record(temp_db, monkeypatch, tmp_path):
    """No anchors/<date>.json -> proof_valid null with a reason."""
    monkeypatch.setenv("ANCHORS_DIR", str(tmp_path / "anchors"))
    pid = _seed_predictions(temp_db, 1)
    today = datetime.now(timezone.utc).date().isoformat()
    commitments.build_batch(today, force=True)
    import os
    os.remove(tmp_path / "anchors" / f"{today}.json")
    view = commitments.prediction_commitment(pid)
    assert view["anchor"]["proof_valid"] is None
    assert "missing" in view["anchor"]["proof_reason"]


def test_ots_unavailable(temp_db, monkeypatch, tmp_path):
    monkeypatch.setenv("ANCHORS_DIR", str(tmp_path / "anchors"))
    monkeypatch.setattr(commitments, "_ots_bin", lambda: None)
    _seed_predictions(temp_db, 1)
    today = datetime.now(timezone.utc).date().isoformat()
    commitments.build_batch(today, force=True)
    assert commitments.stamp_ots(today)["status"] == "unavailable"


def test_ots_stamp_success_and_error(temp_db, monkeypatch, tmp_path):
    monkeypatch.setenv("ANCHORS_DIR", str(tmp_path / "anchors"))
    monkeypatch.setattr(commitments, "_ots_bin", lambda: "/usr/bin/ots")
    _seed_predictions(temp_db, 1)
    today = datetime.now(timezone.utc).date().isoformat()
    commitments.build_batch(today, force=True)

    class R:
        def __init__(self, code=0):
            self.returncode, self.stdout, self.stderr = code, "ok", ""

    def fake_run_ok(cmd, **kw):
        open(cmd[2] + ".ots", "wb").write(b"ots-bytes")
        return R()
    monkeypatch.setattr(commitments.subprocess, "run", fake_run_ok)
    r = commitments.stamp_ots(today)
    assert r["status"] == "pending"
    assert db.get_anchor_by_date(today)["ots_status"] == "pending"

    monkeypatch.setattr(commitments.subprocess, "run",
                        lambda cmd, **kw: R(code=1))
    r = commitments.stamp_ots(today)
    assert r["status"] == "error"
