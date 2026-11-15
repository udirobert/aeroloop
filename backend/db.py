"""SQLite persistence for predictions, readings, errors, strategies."""
from __future__ import annotations

import json
import os
import sqlite3
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
        """
    )
    cols = {r["name"] for r in c.execute("PRAGMA table_info(proposals)")}
    if "provider_evidence" not in cols:
        c.execute("ALTER TABLE proposals ADD COLUMN provider_evidence TEXT")
    c.commit()
    c.close()


def save_prediction(p) -> int:
    c = _conn()
    cur = c.execute(
        """INSERT INTO predictions (station_id, timestamp, predicted_pm25, units,
           confidence, strategy_version, agent_version, inputs, source_timestamps)
           VALUES (?,?,?,?,?,?,?,?,?)""",
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
        ),
    )
    c.commit()
    rid = cur.lastrowid
    c.close()
    return rid


def save_reading(r) -> int:
    c = _conn()
    cur = c.execute(
        """INSERT INTO ground_readings (station_id, timestamp, measured_pm25, units, source)
           VALUES (?,?,?,?,?)""",
        (r.station_id, r.timestamp.isoformat(), r.measured_pm25, r.units, r.source),
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
