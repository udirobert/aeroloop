"""Pre-truth commitments and daily Merkle anchors.

Every saved prediction carries a canonical commit_payload hashed to commit_hash
at save time — before its ground truth could exist. Each day the un-anchored
commitments are folded into a Merkle tree; the root is written as a public
record under anchors/ and timestamped on Bitcoin (OpenTimestamps) and Base.

Merkle scheme "aeroloop-merkle-v1" (domain-separated):
    leaf     = sha256(0x00 || commit_hash_bytes)
    internal = sha256(0x01 || left || right)
    odd node count at a level -> duplicate the last node
    leaves ordered by prediction id

OpenTimestamps: `ots stamp anchors/<date>.root` where the file holds the 32 raw
root bytes. OTS timestamps sha256(file), i.e. it commits to
sha256(root_bytes) — documented in anchors/<date>.json so verifiers hash the
file, not the hex string.
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
from datetime import date as _date
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import db

ANCHORS_DIR = os.getenv(
    "ANCHORS_DIR",
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "anchors"),
)
OTS_TIMEOUT_S = 60

SCHEME = "aeroloop-merkle-v1 (leaf=sha256(0x00||h), node=sha256(0x01||l||r), dup-last)"
COMMITTED_AT_NOTE = (
    "self-reported by the AeroLoop server; "
    "publicly proven only up to the anchor time"
)


def _anchors_dir() -> str:
    d = os.getenv("ANCHORS_DIR", ANCHORS_DIR)
    os.makedirs(d, exist_ok=True)
    return d


# ---------------------------------------------------------------------------
# Merkle tree
# ---------------------------------------------------------------------------

def _leaf(commit_hash: str) -> bytes:
    return hashlib.sha256(b"\x00" + bytes.fromhex(commit_hash)).digest()


def _node(left: bytes, right: bytes) -> bytes:
    return hashlib.sha256(b"\x01" + left + right).digest()


def merkle_root(commit_hashes: List[str]) -> str:
    """Hex Merkle root over commit hashes (ordered). Empty -> sha256 of nothing."""
    if not commit_hashes:
        return hashlib.sha256(b"").hexdigest()
    level = [_leaf(h) for h in commit_hashes]
    while len(level) > 1:
        if len(level) % 2 == 1:
            level = level + [level[-1]]
        level = [_node(level[i], level[i + 1]) for i in range(0, len(level), 2)]
    return level[0].hex()


def merkle_proof(commit_hashes: List[str], index: int) -> List[Dict[str, str]]:
    """Sibling path for commit_hashes[index]: [{"side":"L"|"R","hash":hex}]."""
    if not (0 <= index < len(commit_hashes)):
        raise IndexError(index)
    proof: List[Dict[str, str]] = []
    level = [_leaf(h) for h in commit_hashes]
    idx = index
    while len(level) > 1:
        if len(level) % 2 == 1:
            level = level + [level[-1]]
        sibling = idx + 1 if idx % 2 == 0 else idx - 1
        proof.append({
            "side": "R" if idx % 2 == 0 else "L",
            "hash": level[sibling].hex(),
        })
        level = [_node(level[i], level[i + 1]) for i in range(0, len(level), 2)]
        idx //= 2
    return proof


def verify_proof(commit_hash: str, proof: List[Dict[str, str]], root: str) -> bool:
    node = _leaf(commit_hash)
    for step in proof:
        sib = bytes.fromhex(step["hash"])
        node = _node(node, sib) if step["side"] == "R" else _node(sib, node)
    return node.hex() == root


# ---------------------------------------------------------------------------
# Daily batch
# ---------------------------------------------------------------------------

def build_batch(batch_date: str, force: bool = False) -> Dict[str, Any]:
    """Fold a day's un-anchored commitments into a Merkle root + public record.

    Idempotent: an existing anchor for the date is returned; no leaves -> a
    no-op result. Dates >= today (UTC) are refused unless force=True.
    """
    today = datetime.now(timezone.utc).date()
    try:
        day = _date.fromisoformat(batch_date)
    except ValueError:
        return {"status": "error", "error": f"bad date '{batch_date}' (want YYYY-MM-DD)"}
    if day >= today and not force:
        return {"status": "error",
                "error": f"refusing to anchor {batch_date}: day not finished (UTC)"}

    existing = db.get_anchor_by_date(batch_date)
    if existing:
        existing["status"] = "exists"
        return existing

    leaves = db.get_committed_predictions(batch_date)
    if not leaves:
        return {"status": "empty", "batch_date": batch_date, "n_leaves": 0}

    hashes = [p["commit_hash"] for p in leaves]
    leaf_ids = [p["id"] for p in leaves]
    root = merkle_root(hashes)
    anchor = {
        "batch_date": batch_date,
        "root": root,
        "n_leaves": len(leaves),
        "leaf_ids": leaf_ids,
        "created_at": db._utcnow(),
    }
    anchor_id = db.save_anchor(anchor)
    db.set_prediction_anchor(anchor_id, leaf_ids)

    record = {
        "date": batch_date,
        "root": root,
        "n_leaves": len(leaves),
        "leaves": [{"prediction_id": p["id"], "commit_hash": p["commit_hash"]}
                   for p in leaves],
        "scheme": SCHEME,
        "ots_note": "anchors/<date>.root contains the 32 raw root bytes; "
                    "OpenTimestamps commits to sha256(that file).",
    }
    record_path = os.path.join(_anchors_dir(), f"{batch_date}.json")
    with open(record_path, "w") as f:
        json.dump(record, f, indent=2)

    anchor.update({"id": anchor_id, "status": "built", "record_file": record_path})
    return anchor


# ---------------------------------------------------------------------------
# OpenTimestamps
# ---------------------------------------------------------------------------

def _ots_bin() -> Optional[str]:
    return shutil.which("ots")


def _ots_env() -> Dict[str, str]:
    """ots calls out over urllib; give it CA roots when the platform store
    is missing (framework Python on macOS has none by default)."""
    env = dict(os.environ)
    if "SSL_CERT_FILE" not in env:
        try:
            import certifi
            env["SSL_CERT_FILE"] = certifi.where()
        except ImportError:
            pass
    return env


def stamp_ots(batch_date: str, timeout_s: int = OTS_TIMEOUT_S) -> Dict[str, Any]:
    """Write anchors/<date>.root (raw root bytes) and run `ots stamp` on it.

    Statuses: "pending" (stamped, awaiting Bitcoin confirmation),
    "unavailable" (ots CLI not installed), "error".
    """
    anchor = db.get_anchor_by_date(batch_date)
    if not anchor:
        return {"status": "error", "error": f"no anchor for {batch_date}"}
    if not _ots_bin():
        return {"status": "unavailable"}

    root_file = os.path.join(_anchors_dir(), f"{batch_date}.root")
    with open(root_file, "wb") as f:
        f.write(bytes.fromhex(anchor["root"]))
    ots_file = root_file + ".ots"
    try:
        r = subprocess.run(
            [_ots_bin(), "stamp", root_file],
            capture_output=True, text=True, timeout=timeout_s, env=_ots_env(),
        )
    except subprocess.TimeoutExpired:
        db.update_anchor(anchor["id"], ots_status="error",
                         ots_error="ots stamp timed out")
        return {"status": "error", "error": "ots stamp timed out"}
    if r.returncode != 0 or not os.path.exists(ots_file):
        err = (r.stderr or r.stdout).strip()[:300]
        db.update_anchor(anchor["id"], ots_status="error", ots_error=err)
        return {"status": "error", "error": err}
    db.update_anchor(anchor["id"], ots_status="pending", ots_file=ots_file,
                     ots_updated_at=db._utcnow(), ots_error=None)
    return {"status": "pending", "ots_file": ots_file,
            "output": (r.stdout or r.stderr).strip()[:300]}


def upgrade_pending_ots(timeout_s: int = OTS_TIMEOUT_S) -> List[Dict[str, Any]]:
    """Run `ots upgrade` on every pending anchor; mark "complete" when a
    Bitcoin attestation lands. Still-pending stays pending."""
    if not _ots_bin():
        return [{"status": "unavailable"}]
    results = []
    for a in db.get_anchors():
        if a.get("ots_status") != "pending" or not a.get("ots_file"):
            continue
        try:
            r = subprocess.run(
                [_ots_bin(), "upgrade", a["ots_file"]],
                capture_output=True, text=True, timeout=timeout_s, env=_ots_env(),
            )
        except subprocess.TimeoutExpired:
            results.append({"batch_date": a["batch_date"], "status": "error",
                            "error": "ots upgrade timed out"})
            continue
        out = ((r.stdout or "") + (r.stderr or "")).lower()
        if "success" in out or "attestation" in out:
            db.update_anchor(a["id"], ots_status="complete",
                             ots_updated_at=db._utcnow())
            results.append({"batch_date": a["batch_date"], "status": "complete"})
        else:
            results.append({"batch_date": a["batch_date"], "status": "pending",
                            "output": (r.stdout or r.stderr).strip()[:200]})
    return results


# ---------------------------------------------------------------------------
# Public verification view
# ---------------------------------------------------------------------------

def explorer_url(chain_id: Optional[int], tx: Optional[str]) -> Optional[str]:
    if not tx:
        return None
    host = "sepolia.basescan.org" if chain_id == 84532 else "basescan.org"
    return f"https://{host}/tx/{tx}"


def _iso(s: Optional[str]) -> Optional[datetime]:
    if not s:
        return None
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00"))
    except ValueError:
        return None


def prediction_commitment(prediction_id: int) -> Optional[Dict[str, Any]]:
    """Everything a third party needs to verify 'saved before its truth'.

    committed_at is self-reported by this server; the only publicly provable
    bound is the anchor time (Base block time once confirmed, or the
    OpenTimestamps Bitcoin attestation). The Merkle proof is rebuilt from the
    published anchors/<date>.json record, not from mutable DB rows.
    """
    p = db.get_prediction(prediction_id)
    if p is None:
        return None

    if not p.get("commit_hash"):
        return {
            "prediction_id": prediction_id,
            "kind": "uncommitted",
            "committed_at": None,
            "commit_payload": None,
            "commit_hash": None,
            "recomputed_hash": None,
            "hash_matches": None,
            "reading": None,
            "reading_recorded_after_commit": None,
            "committed_at_note": COMMITTED_AT_NOTE,
            "existed_by": None,
            "existed_by_source": None,
            "target_after_existed_by": None,
            "anchor": None,
        }

    recomputed = hashlib.sha256(p["commit_payload"].encode("utf-8")).hexdigest()
    reading = db.get_reading(p["station_id"], p["timestamp"])
    reading_after = None
    if reading and reading.get("recorded_at"):
        reading_after = reading["recorded_at"] > p["committed_at"]

    anchor_view = None
    existed_by = None
    existed_by_source = None
    target_after = None
    if p.get("anchor_id"):
        anchor_row = next(
            (a for a in db.get_anchors() if a["id"] == p["anchor_id"]), None
        )
        if anchor_row:
            record_path = os.path.join(
                _anchors_dir(), f"{anchor_row['batch_date']}.json"
            )
            proof = None
            proof_valid = None
            proof_reason = None
            published_root = None
            roots_consistent = None
            if os.path.exists(record_path):
                try:
                    record = json.loads(
                        open(record_path, encoding="utf-8").read()
                    )
                    published_root = record.get("root")
                    leaf_hashes = [lf["commit_hash"] for lf in record["leaves"]]
                    recomputed_root = merkle_root(leaf_hashes)
                    roots_consistent = (
                        recomputed_root == published_root == anchor_row["root"]
                    )
                    idx = next(
                        (i for i, lf in enumerate(record["leaves"])
                         if lf["prediction_id"] == prediction_id),
                        None,
                    )
                    if idx is None:
                        proof_valid = False
                        proof_reason = (
                            "prediction_id absent from published leaf list"
                        )
                    else:
                        proof = merkle_proof(leaf_hashes, idx)
                        proof_valid = (
                            verify_proof(leaf_hashes[idx], proof, published_root)
                            and roots_consistent
                        )
                except (json.JSONDecodeError, KeyError, TypeError) as e:
                    proof_reason = f"unreadable published record: {e}"
            else:
                proof_reason = f"published record missing: {record_path}"

            if anchor_row.get("base_status") == "confirmed":
                existed_by = anchor_row.get("base_block_time")
                existed_by_source = anchor_row.get("base_network")
            pred_ts = _iso(p["timestamp"])
            if existed_by and pred_ts:
                target_after = pred_ts > _iso(existed_by)

            anchor_view = {
                "batch_date": anchor_row["batch_date"],
                "root": anchor_row["root"],
                "published_root": published_root,
                "roots_consistent": roots_consistent,
                "proof": proof,
                "proof_valid": proof_valid,
                "proof_reason": proof_reason,
                "ots_status": anchor_row.get("ots_status"),
                "ots_file": anchor_row.get("ots_file"),
                "base_network": anchor_row.get("base_network"),
                "base_tx": anchor_row.get("base_tx"),
                "base_status": anchor_row.get("base_status"),
                "base_block_time": anchor_row.get("base_block_time"),
                "explorer_url": explorer_url(anchor_row.get("base_chain_id"),
                                             anchor_row.get("base_tx")),
            }

    return {
        "prediction_id": prediction_id,
        "kind": p["commit_kind"],
        "committed_at": p["committed_at"],
        "commit_payload": p["commit_payload"],
        "commit_hash": p["commit_hash"],
        "recomputed_hash": recomputed,
        "hash_matches": recomputed == p["commit_hash"],
        "reading": (
            {
                "measured_pm25": reading["measured_pm25"],
                "recorded_at": reading.get("recorded_at"),
                "source": reading["source"],
            }
            if reading else None
        ),
        "reading_recorded_after_commit": reading_after,
        "committed_at_note": COMMITTED_AT_NOTE,
        "existed_by": existed_by,
        "existed_by_source": existed_by_source,
        "target_after_existed_by": target_after,
        "anchor": anchor_view,
    }
