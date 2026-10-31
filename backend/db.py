"""SQLite persistence for predictions, readings, errors, strategies."""
from __future__ import annotations

import json
import os
import sqlite3
from datetime import datetime
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
        """
    )
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
