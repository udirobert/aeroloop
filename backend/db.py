"""SQLite persistence for predictions, readings, errors, strategies."""
from __future__ import annotations

import hashlib
import json
import os
import sqlite3
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

DB_PATH = os.getenv(
    "DATABASE_PATH",
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "data", "aeroloop.db"),
)


def _conn() -> sqlite3.Connection:
    os.makedirs(os.path.dirname(os.path.abspath(DB_PATH)), exist_ok=True)
    c = sqlite3.connect(DB_PATH)
    c.row_factory = sqlite3.Row
    return c


def init_db() -> None:
    c = _conn()
    c.executescript(
        """
        CREATE TABLE IF NOT EXISTS predictions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            station_id TEXT NOT NULL,
            timestamp TEXT NOT NULL,
            predicted_pm25 REAL NOT NULL,
            units TEXT NOT NULL,
            confidence REAL,
            strategy_version TEXT NOT NULL,
            agent_version TEXT NOT NULL,
            inputs TEXT NOT NULL,
            source_timestamps TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS ground_readings (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            station_id TEXT NOT NULL,
            timestamp TEXT NOT NULL,
            measured_pm25 REAL NOT NULL,
            units TEXT NOT NULL,
            source TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS errors (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            prediction_id INTEGER NOT NULL,
            station_id TEXT NOT NULL,
            timestamp TEXT NOT NULL,
            predicted REAL NOT NULL,
            actual REAL NOT NULL,
            error REAL NOT NULL,
            abs_error REAL NOT NULL,
            squared_error REAL NOT NULL
        );
        CREATE TABLE IF NOT EXISTS strategies (
            version TEXT PRIMARY KEY,
            description TEXT NOT NULL,
            params TEXT NOT NULL,
            created_at TEXT NOT NULL,
            parent_version TEXT
        );
        CREATE TABLE IF NOT EXISTS tournament_runs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            created_at TEXT NOT NULL,
            incumbent_version TEXT,
            tune_n INTEGER,
            holdout_n INTEGER,
            windows INTEGER,
            winner TEXT,
            strategy_version TEXT,
            outcome TEXT,
            incumbent_scores TEXT
        );
        CREATE TABLE IF NOT EXISTS proposals (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            run_id INTEGER NOT NULL,
            proposer TEXT NOT NULL,
            label TEXT,
            model TEXT,
            uses_serv INTEGER,
            status TEXT,
            error TEXT,
            params TEXT,
            analysis TEXT,
            holdout TEXT,
            windows_won INTEGER,
            eligible INTEGER,
            latency_ms INTEGER,
            prompt_tokens INTEGER,
            completion_tokens INTEGER,
            cost_usd REAL,
            gate_status TEXT,
            reppo TEXT,
            provider_evidence TEXT
        );
        CREATE TABLE IF NOT EXISTS anchors (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            batch_date TEXT UNIQUE,
            root TEXT,
            n_leaves INTEGER,
            leaf_ids TEXT,
            created_at TEXT,
            ots_status TEXT,
            ots_file TEXT,
            ots_updated_at TEXT,
            base_network TEXT,
            base_chain_id INTEGER,
            base_tx TEXT,
            base_block INTEGER,
            base_status TEXT,
            base_block_time TEXT,
            base_error TEXT,
            ots_error TEXT
        );
        CREATE TABLE IF NOT EXISTS reference_sites (
            code TEXT NOT NULL,
            species TEXT NOT NULL,
            name TEXT,
            lat REAL,
            lon REAL,
            network TEXT NOT NULL DEFAULT 'LAQN',
            valid_hours INTEGER,
            expected_hours INTEGER,
            coverage REAL,
            window_start TEXT,
            window_end TEXT,
            probed_at TEXT,
            qualifies INTEGER,
            PRIMARY KEY (code, species)
        );
        CREATE TABLE IF NOT EXISTS sensors (
            uid TEXT PRIMARY KEY,
            source TEXT NOT NULL,
            lat REAL,
            lon REAL,
            indoor INTEGER NOT NULL DEFAULT 0,
            meta TEXT,
            listed_at TEXT
        );
        CREATE TABLE IF NOT EXISTS sensor_readings (
            uid TEXT NOT NULL,
            timestamp TEXT NOT NULL,
            species TEXT NOT NULL,
            value REAL,
            flags TEXT,
            PRIMARY KEY (uid, timestamp, species)
        );
        CREATE TABLE IF NOT EXISTS sensor_audits (
            uid TEXT NOT NULL,
            species TEXT NOT NULL,
            reference TEXT NOT NULL,
            distance_m REAL,
            sensor_type TEXT,
            window_start TEXT NOT NULL,
            window_end TEXT NOT NULL,
            sensor_hours INTEGER,
            reference_hours INTEGER,
            paired_hours INTEGER,
            score TEXT,
            audited_at TEXT NOT NULL,
            PRIMARY KEY (uid, species, window_start, window_end)
        );
        """
    )
    cols = {r["name"] for r in c.execute("PRAGMA table_info(proposals)")}
    if "provider_evidence" not in cols:
        c.execute("ALTER TABLE proposals ADD COLUMN provider_evidence TEXT")
    # commitment columns (aeroloop-merkle-v1)
    pred_cols = {r["name"] for r in c.execute("PRAGMA table_info(predictions)")}
    for col in ("commit_payload", "commit_hash", "committed_at", "commit_kind"):
        if col not in pred_cols:
            c.execute(f"ALTER TABLE predictions ADD COLUMN {col} TEXT")
    if "anchor_id" not in pred_cols:
        c.execute("ALTER TABLE predictions ADD COLUMN anchor_id INTEGER")
    read_cols = {r["name"] for r in c.execute("PRAGMA table_info(ground_readings)")}
    if "recorded_at" not in read_cols:
        c.execute("ALTER TABLE ground_readings ADD COLUMN recorded_at TEXT")
    anch_cols = {r["name"] for r in c.execute("PRAGMA table_info(anchors)")}
    if "base_block_time" not in anch_cols:
        c.execute("ALTER TABLE anchors ADD COLUMN base_block_time TEXT")
    c.commit()
    c.close()


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _commit_fields(p, kind: str) -> Dict[str, Any]:
    """Canonical commitment payload + hash, built BEFORE the row is inserted.

    The stored commit_payload string is what gets re-hashed on verification, so
    the hash never depends on float re-serialisation.
    """
    committed_at = _utcnow()
    payload = {
        "v": 1,
        "kind": kind,
        "station_id": p.station_id,
        "timestamp": p.timestamp.isoformat(),
        "predicted_pm25": p.predicted_pm25,
        "units": p.units,
        "strategy_version": p.strategy_version,
        "agent_version": p.agent_version,
        "inputs": p.inputs,
        "source_timestamps": p.source_timestamps,
        "committed_at": committed_at,
    }
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"),
                           ensure_ascii=False)
    return {
        "commit_payload": canonical,
        "commit_hash": hashlib.sha256(canonical.encode("utf-8")).hexdigest(),
        "committed_at": committed_at,
        "commit_kind": kind,
    }


def save_prediction(p, kind: str = "live") -> int:
    """Insert a prediction with its pre-truth commitment.

    kind: "live" (real-time predict), "simulated" (demo-day), "hindcast"
    (backfill over already-ratified truth — never masquerades as pre-truth).
    """
    commit = _commit_fields(p, kind)
    c = _conn()
    cur = c.execute(
        """INSERT INTO predictions (station_id, timestamp, predicted_pm25, units,
           confidence, strategy_version, agent_version, inputs, source_timestamps,
           commit_payload, commit_hash, committed_at, commit_kind)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (
            p.station_id,
            p.timestamp.isoformat(),
            p.predicted_pm25,
            p.units,
            p.confidence,
            p.strategy_version,
            p.agent_version,
            json.dumps(p.inputs),
            json.dumps(p.source_timestamps),
            commit["commit_payload"],
            commit["commit_hash"],
            commit["committed_at"],
            commit["commit_kind"],
        ),
    )
    c.commit()
    rid = cur.lastrowid
    c.close()
    return rid


def save_reading(r) -> int:
    c = _conn()
    cur = c.execute(
        """INSERT INTO ground_readings (station_id, timestamp, measured_pm25, units,
           source, recorded_at)
           VALUES (?,?,?,?,?,?)""",
        (r.station_id, r.timestamp.isoformat(), r.measured_pm25, r.units, r.source,
         _utcnow()),
    )
    c.commit()
    rid = cur.lastrowid
    c.close()
    return rid


def save_error(e) -> int:
    c = _conn()
    cur = c.execute(
        """INSERT INTO errors (prediction_id, station_id, timestamp, predicted, actual,
           error, abs_error, squared_error) VALUES (?,?,?,?,?,?,?,?)""",
        (
            e.prediction_id,
            e.station_id,
            e.timestamp.isoformat(),
            e.predicted,
            e.actual,
            e.error,
            e.abs_error,
            e.squared_error,
        ),
    )
    c.commit()
    rid = cur.lastrowid
    c.close()
    return rid


def save_strategy(s) -> None:
    c = _conn()
    c.execute(
        """INSERT OR REPLACE INTO strategies (version, description, params, created_at, parent_version)
           VALUES (?,?,?,?,?)""",
        (s.version, s.description, json.dumps(s.params), s.created_at.isoformat(), s.parent_version),
    )
    c.commit()
    c.close()


def get_predictions(station_id: Optional[str] = None) -> List[Dict[str, Any]]:
    c = _conn()
    if station_id:
        rows = c.execute(
            "SELECT * FROM predictions WHERE station_id=? ORDER BY timestamp", (station_id,)
        ).fetchall()
    else:
        rows = c.execute("SELECT * FROM predictions ORDER BY timestamp").fetchall()
    c.close()
    return [dict(r) for r in rows]


def get_readings(station_id: Optional[str] = None) -> List[Dict[str, Any]]:
    c = _conn()
    if station_id:
        rows = c.execute(
            "SELECT * FROM ground_readings WHERE station_id=? ORDER BY timestamp", (station_id,)
        ).fetchall()
    else:
        rows = c.execute("SELECT * FROM ground_readings ORDER BY timestamp").fetchall()
    c.close()
    return [dict(r) for r in rows]


def get_errors() -> List[Dict[str, Any]]:
    c = _conn()
    rows = c.execute("SELECT * FROM errors ORDER BY timestamp").fetchall()
    c.close()
    return [dict(r) for r in rows]


def get_strategies() -> List[Dict[str, Any]]:
    c = _conn()
    rows = c.execute("SELECT * FROM strategies ORDER BY created_at").fetchall()
    c.close()
    return [dict(r) for r in rows]


_PROPOSAL_JSON_FIELDS = ("params", "analysis", "holdout", "reppo", "provider_evidence")


def save_tournament_run(run: Dict[str, Any]) -> int:
    """Persist one tournament run + its proposal rows. Returns run id."""
    c = _conn()
    cur = c.execute(
        """INSERT INTO tournament_runs (created_at, incumbent_version, tune_n, holdout_n,
           windows, winner, strategy_version, outcome, incumbent_scores)
           VALUES (?,?,?,?,?,?,?,?,?)""",
        (
            run["created_at"],
            run.get("incumbent_version"),
            run.get("tune_n"),
            run.get("holdout_n"),
            run.get("windows"),
            run.get("winner"),
            run.get("strategy_version"),
            run.get("outcome"),
            json.dumps(run.get("incumbent_scores")),
        ),
    )
    run_id = cur.lastrowid
    for p in run.get("proposals", []):
        evidence = {k: p[k] for k in ("response_id", "finish_reason",
                                      "cached_tokens", "reasoning_tokens",
                                      "response_schema")
                    if p.get(k) is not None}
        c.execute(
            """INSERT INTO proposals (run_id, proposer, label, model, uses_serv, status,
               error, params, analysis, holdout, windows_won, eligible, latency_ms,
               prompt_tokens, completion_tokens, cost_usd, gate_status, reppo,
               provider_evidence)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                run_id,
                p.get("proposer"),
                p.get("label"),
                p.get("model"),
                int(bool(p.get("uses_serv"))),
                p.get("status"),
                p.get("error"),
                json.dumps(p.get("params")) if p.get("params") is not None else None,
                json.dumps(p.get("analysis")) if p.get("analysis") is not None else None,
                json.dumps(p.get("holdout")) if p.get("holdout") is not None else None,
                p.get("windows_won"),
                int(bool(p.get("eligible"))) if p.get("eligible") is not None else None,
                p.get("latency_ms"),
                p.get("prompt_tokens"),
                p.get("completion_tokens"),
                p.get("cost_usd"),
                p.get("gate_status"),
                json.dumps(p.get("reppo")) if p.get("reppo") is not None else None,
                json.dumps(evidence) if evidence else None,
            ),
        )
    c.commit()
    c.close()
    return run_id


def _decode_proposal(row: Dict[str, Any]) -> Dict[str, Any]:
    r = dict(row)
    for f in _PROPOSAL_JSON_FIELDS:
        if r.get(f) is not None:
            r[f] = json.loads(r[f])
    r["uses_serv"] = bool(r.get("uses_serv"))
    r["eligible"] = bool(r.get("eligible")) if r.get("eligible") is not None else None
    return r


def get_tournament_runs(limit: int = 20) -> List[Dict[str, Any]]:
    c = _conn()
    rows = c.execute(
        "SELECT * FROM tournament_runs ORDER BY id DESC LIMIT ?", (limit,)
    ).fetchall()
    c.close()
    out = []
    for r in rows:
        d = dict(r)
        if d.get("incumbent_scores"):
            d["incumbent_scores"] = json.loads(d["incumbent_scores"])
        out.append(d)
    return out


def get_tournament_run(run_id: int) -> Optional[Dict[str, Any]]:
    c = _conn()
    run = c.execute("SELECT * FROM tournament_runs WHERE id=?", (run_id,)).fetchone()
    if run is None:
        c.close()
        return None
    props = c.execute(
        "SELECT * FROM proposals WHERE run_id=? ORDER BY id", (run_id,)
    ).fetchall()
    c.close()
    d = dict(run)
    if d.get("incumbent_scores"):
        d["incumbent_scores"] = json.loads(d["incumbent_scores"])
    d["proposals"] = [_decode_proposal(p) for p in props]
    return d


# ---------------------------------------------------------------------------
# Commitments & anchors
# ---------------------------------------------------------------------------

def get_prediction(prediction_id: int) -> Optional[Dict[str, Any]]:
    c = _conn()
    row = c.execute("SELECT * FROM predictions WHERE id=?", (prediction_id,)).fetchone()
    c.close()
    return dict(row) if row else None


def get_reading(station_id: str, timestamp: str) -> Optional[Dict[str, Any]]:
    c = _conn()
    row = c.execute(
        "SELECT * FROM ground_readings WHERE station_id=? AND timestamp=?",
        (station_id, timestamp),
    ).fetchone()
    c.close()
    return dict(row) if row else None


def get_committed_predictions(date: Optional[str] = None) -> List[Dict[str, Any]]:
    """Predictions with a commit_hash. If date given, committed_at's UTC date."""
    c = _conn()
    if date:
        rows = c.execute(
            """SELECT * FROM predictions WHERE commit_hash IS NOT NULL
               AND anchor_id IS NULL AND substr(committed_at, 1, 10)=?
               ORDER BY id""",
            (date,),
        ).fetchall()
    else:
        rows = c.execute(
            "SELECT * FROM predictions WHERE commit_hash IS NOT NULL ORDER BY id"
        ).fetchall()
    c.close()
    return [dict(r) for r in rows]


def set_prediction_anchor(anchor_id: int, leaf_ids: List[int]) -> None:
    c = _conn()
    c.executemany(
        "UPDATE predictions SET anchor_id=? WHERE id=?",
        [(anchor_id, pid) for pid in leaf_ids],
    )
    c.commit()
    c.close()


def save_anchor(a: Dict[str, Any]) -> int:
    c = _conn()
    cur = c.execute(
        """INSERT OR IGNORE INTO anchors (batch_date, root, n_leaves, leaf_ids,
           created_at, ots_status, ots_file, base_network, base_chain_id, base_tx,
           base_block, base_status, base_error, ots_error)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (
            a["batch_date"], a["root"], a["n_leaves"], json.dumps(a["leaf_ids"]),
            a["created_at"], a.get("ots_status"), a.get("ots_file"),
            a.get("base_network"), a.get("base_chain_id"), a.get("base_tx"),
            a.get("base_block"), a.get("base_status"), a.get("base_error"),
            a.get("ots_error"),
        ),
    )
    c.commit()
    rid = cur.lastrowid
    if not rid:  # INSERT OR IGNORE hit the UNIQUE batch_date — fetch existing
        row = c.execute(
            "SELECT id FROM anchors WHERE batch_date=?", (a["batch_date"],)
        ).fetchone()
        rid = row["id"] if row else None
    c.close()
    return rid


def get_anchor_by_date(batch_date: str) -> Optional[Dict[str, Any]]:
    c = _conn()
    row = c.execute("SELECT * FROM anchors WHERE batch_date=?", (batch_date,)).fetchone()
    c.close()
    if not row:
        return None
    d = dict(row)
    d["leaf_ids"] = json.loads(d["leaf_ids"]) if d.get("leaf_ids") else []
    return d


def get_anchors(limit: int = 60) -> List[Dict[str, Any]]:
    c = _conn()
    rows = c.execute(
        "SELECT * FROM anchors ORDER BY batch_date DESC LIMIT ?", (limit,)
    ).fetchall()
    c.close()
    out = []
    for r in rows:
        d = dict(r)
        d["leaf_ids"] = json.loads(d["leaf_ids"]) if d.get("leaf_ids") else []
        out.append(d)
    return out


def update_anchor(anchor_id: int, **fields: Any) -> None:
    allowed = {
        "root", "n_leaves", "leaf_ids", "ots_status", "ots_file", "ots_updated_at",
        "base_network", "base_chain_id", "base_tx", "base_block", "base_status",
        "base_block_time", "base_error", "ots_error",
    }
    sets, vals = [], []
    for k, v in fields.items():
        if k not in allowed:
            raise ValueError(f"unknown anchor field {k}")
        sets.append(f"{k}=?")
        vals.append(json.dumps(v) if k == "leaf_ids" and not isinstance(v, str) else v)
    c = _conn()
    c.execute(f"UPDATE anchors SET {', '.join(sets)} WHERE id=?", (*vals, anchor_id))
    c.commit()
    c.close()


def upsert_reference_site(s: Dict[str, Any]) -> None:
    c = _conn()
    c.execute(
        """INSERT OR REPLACE INTO reference_sites
           (code, species, name, lat, lon, network, valid_hours, expected_hours,
            coverage, window_start, window_end, probed_at, qualifies)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (s["code"], s["species"], s.get("name"), s.get("lat"), s.get("lon"),
         s.get("network", "LAQN"), s.get("valid_hours"), s.get("expected_hours"),
         s.get("coverage"), s.get("window_start"), s.get("window_end"),
         s.get("probed_at"), int(bool(s.get("qualifies")))),
    )
    c.commit()
    c.close()


def get_reference_sites(species: Optional[str] = None,
                        qualifying: Optional[bool] = None
                        ) -> List[Dict[str, Any]]:
    q = "SELECT * FROM reference_sites WHERE 1=1"
    args: list = []
    if species:
        q += " AND species=?"
        args.append(species)
    if qualifying is not None:
        q += " AND qualifies=?"
        args.append(1 if qualifying else 0)
    q += " ORDER BY code"
    c = _conn()
    rows = c.execute(q, args).fetchall()
    c.close()
    return [dict(r) for r in rows]


def upsert_sensor(s: Dict[str, Any]) -> None:
    c = _conn()
    c.execute(
        """INSERT OR REPLACE INTO sensors (uid, source, lat, lon, indoor, meta,
           listed_at) VALUES (?,?,?,?,?,?,?)""",
        (s["uid"], s["source"], s.get("lat"), s.get("lon"),
         int(bool(s.get("indoor"))), json.dumps(s.get("meta") or {}),
         s.get("listed_at")),
    )
    c.commit()
    c.close()


def get_sensors(source: Optional[str] = None) -> List[Dict[str, Any]]:
    c = _conn()
    if source:
        rows = c.execute("SELECT * FROM sensors WHERE source=?", (source,)).fetchall()
    else:
        rows = c.execute("SELECT * FROM sensors").fetchall()
    c.close()
    out = []
    for r in rows:
        d = dict(r)
        d["meta"] = json.loads(d["meta"]) if d.get("meta") else {}
        out.append(d)
    return out


def save_sensor_reading(uid: str, timestamp: str, species: str,
                        value: Optional[float], flags: Dict[str, Any]) -> None:
    c = _conn()
    c.execute(
        """INSERT OR REPLACE INTO sensor_readings (uid, timestamp, species,
           value, flags) VALUES (?,?,?,?,?)""",
        (uid, timestamp, species, value, json.dumps(flags)),
    )
    c.commit()
    c.close()


def get_sensor_readings(uid: Optional[str] = None,
                        species: Optional[str] = None) -> List[Dict[str, Any]]:
    q = "SELECT * FROM sensor_readings WHERE 1=1"
    args: list = []
    if uid:
        q += " AND uid=?"
        args.append(uid)
    if species:
        q += " AND species=?"
        args.append(species)
    c = _conn()
    rows = c.execute(q, args).fetchall()
    c.close()
    out = []
    for r in rows:
        d = dict(r)
        d["flags"] = json.loads(d["flags"]) if d.get("flags") else {}
        out.append(d)
    return out


def save_sensor_audit(a: Dict[str, Any]) -> None:
    """Persist one scored sensor-vs-reference audit row."""
    c = _conn()
    c.execute(
        """INSERT OR REPLACE INTO sensor_audits
           (uid, species, reference, distance_m, sensor_type, window_start,
            window_end, sensor_hours, reference_hours, paired_hours, score,
            audited_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
        (a["uid"], a["species"], a["reference"], a.get("distance_m"),
         a.get("sensor_type"), a["window_start"], a["window_end"],
         a.get("sensor_hours"), a.get("reference_hours"),
         a.get("paired_hours"), json.dumps(a.get("score") or {}),
         a["audited_at"]),
    )
    c.commit()
    c.close()


def get_sensor_audits(species: Optional[str] = None) -> List[Dict[str, Any]]:
    """Latest audit per (uid, species), most recent audit first."""
    q = """SELECT * FROM sensor_audits WHERE (uid, species, audited_at) IN
           (SELECT uid, species, MAX(audited_at) FROM sensor_audits
            GROUP BY uid, species)"""
    args: list = []
    if species:
        q += " AND species=?"
        args.append(species)
    q += " ORDER BY species, distance_m"
    c = _conn()
    rows = c.execute(q, args).fetchall()
    c.close()
    out = []
    for r in rows:
        d = dict(r)
        d["score"] = json.loads(d["score"]) if d.get("score") else {}
        out.append(d)
    return out
