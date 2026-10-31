"""AeroLoop FastAPI backend: prediction + ground truth + self-improvement."""
from __future__ import annotations

import json
import os
import random
import sys
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

sys.path.insert(0, os.path.dirname(__file__))

from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(__file__), ".env"))  # before modules read env vars

from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

import agent
import data_sources
import db
import evaluation
import prediction
from models import ErrorRecord, GroundReading, Prediction, Strategy

app = FastAPI(title="AeroLoop", version="0.1.0")

FRONTEND_DIR = os.path.join(os.path.dirname(__file__), "..", "frontend")


@app.on_event("startup")
def _startup():
    db.init_db()
    # seed strategies only once — re-seeding would refresh created_at and
    # scramble the "latest incumbent" ordering
    existing = {s["version"] for s in db.get_strategies()}
    for v, desc, params in [
        ("v1-baseline", "Trust CAMS model PM2.5 with light humidity correction.", {}),
        ("v2-improved", "Model PM2.5 + humidity/wind/precip correction + bias.", prediction.STRATEGY_REGISTRY["v2-improved"]["params"]),
    ]:
        if v not in existing:
            db.save_strategy(Strategy(version=v, description=desc, params=params, created_at=datetime.utcnow()))


def _resolve_strategy(version: str) -> Tuple[str, Dict[str, Any]]:
    """Return (kind, params): 'v1' baseline fn, or 'v2' parametric fn with params."""
    if version == "v1-baseline":
        return "v1", {}
    if version == "latest":
        return "v2", agent._incumbent()[1]
    # note: "latest" = incumbent; v1/v2 names are reserved seeds
    if version == "v2-improved":
        return "v2", dict(prediction.STRATEGY_REGISTRY["v2-improved"]["params"])
    stored = next((s for s in db.get_strategies() if s["version"] == version), None)
    if stored:
        params = json.loads(stored["params"])
        if params.get("kind") == "tabpfn":
            raise HTTPException(400, "tabpfn strategies are audit records; live prediction uses parametric strategies")
        return "v2", params
    raise HTTPException(400, f"unknown strategy '{version}'")


def _run_strategy(kind: str, params: Dict[str, Any], features: Dict[str, Any]) -> float:
    if kind == "v1":
        return prediction.predict("v1-baseline", features)
    return prediction.predict("v2-improved", features, params)


def _matched_pairs() -> List[Dict[str, Any]]:
    """Prediction/reading pairs: features + the actual that arrived later."""
    readings = {(r["station_id"], r["timestamp"]): r["measured_pm25"] for r in db.get_readings()}
    pairs = []
    for p in db.get_predictions():
        key = (p["station_id"], p["timestamp"])
        if key in readings:
            pairs.append({
                "station_id": p["station_id"],
                "timestamp": p["timestamp"],
                "inputs": json.loads(p["inputs"]),
                "actual": readings[key],
            })
    return pairs


class PredictRequest(BaseModel):
    station_id: str = "bloomsbury"
    strategy_version: str = "latest"


@app.get("/health")
def health():
    return {"status": "ok", "stations": list(data_sources.LONDON_STATIONS.keys())}


@app.post("/predict")
async def predict(req: PredictRequest):
    if req.station_id not in data_sources.LONDON_STATIONS:
        raise HTTPException(400, "unknown station")
    lat, lon = data_sources.LONDON_STATIONS[req.station_id]
    aq = await data_sources.fetch_air_quality(lat, lon)
    wx = await data_sources.fetch_weather(lat, lon)
    features = data_sources.align_latest(aq, wx)
    # ground truth is NOT available at prediction time (saved separately)
    ts = datetime.now(timezone.utc)
    kind, params = _resolve_strategy(req.strategy_version)
    pred_val = _run_strategy(kind, params, features)
    p = Prediction(
        station_id=req.station_id,
        timestamp=ts,
        predicted_pm25=pred_val,
        confidence=0.7,
        strategy_version=req.strategy_version,
        agent_version="aeroloop-0.1",
        inputs=features,
        source_timestamps={"aq": features.get("timestamp"), "wx": features.get("timestamp")},
    )
    pid = db.save_prediction(p)
    return {"prediction_id": pid, "prediction": p.model_dump(mode="json")}


@app.post("/ground-truth")
def ground_truth(station_id: str, prediction_id: int):
    preds = db.get_predictions(station_id)
    target = next((p for p in preds if p["id"] == prediction_id), None)
    if not target:
        raise HTTPException(404, "prediction not found")
    ts = datetime.fromisoformat(target["timestamp"])
    model_pm25 = (json.loads(target["inputs"]).get("pm25_model") if target["inputs"] else None) or 10.0
    actual = data_sources.synthetic_ground_reading(station_id, ts, model_pm25)
    reading = GroundReading(station_id=station_id, timestamp=ts, measured_pm25=actual, source="synthetic (offline stand-in)")
    rid = db.save_reading(reading)
    err = target["predicted_pm25"] - actual
    db.save_error(ErrorRecord(
        prediction_id=prediction_id, station_id=station_id, timestamp=ts,
        predicted=target["predicted_pm25"], actual=actual, error=err,
        abs_error=abs(err), squared_error=err * err,
    ))
    return {"reading_id": rid, "measured_pm25": actual, "error": err}


@app.get("/evaluate")
def evaluate(strategy_version: str = "latest"):
    kind, params = _resolve_strategy(strategy_version)
    pairs = _matched_pairs()
    norm = [
        {"station_id": m["station_id"], "timestamp": m["timestamp"],
         "predicted_pm25": _run_strategy(kind, params, m["inputs"])}
        for m in pairs
    ]
    readings = [
        {"station_id": m["station_id"], "timestamp": m["timestamp"], "measured_pm25": m["actual"]}
        for m in pairs
    ]
    result = evaluation.evaluate(norm, readings)
    result["strategy_version"] = strategy_version
    return result


@app.post("/self-improve")
def self_improve():
    pairs = _matched_pairs()
    if len(pairs) < 6:
        raise HTTPException(400, f"need >=6 matched prediction/reading pairs, have {len(pairs)}")
    return agent.run_self_improvement(pairs)


@app.post("/demo-day")
def demo_day(hours: int = 24):
    """Simulate a day of predictions + delayed ground truth across all stations.

    Makes the whole loop demoable offline in one call. Every pair is saved with
    a backdated timestamp so tune/holdout splits behave like real time series.
    """
    rng = random.Random()
    n = 0
    stations = list(data_sources.LONDON_STATIONS)
    for i in range(hours):
        ts = datetime.now(timezone.utc) - timedelta(hours=hours - i)
        for st in stations:
            feats = {
                "pm25_model": round(rng.uniform(5, 30), 1),
                "no2_model": round(rng.uniform(10, 60), 1),
                "humidity": round(rng.uniform(50, 95), 1),
                "wind_speed": round(rng.uniform(2, 15), 1),
                "temperature": round(rng.uniform(5, 20), 1),
                "precipitation": round(max(0.0, rng.gauss(0, 1.2)), 2),
                "timestamp": ts.isoformat(),
            }
            pred_val = prediction.predict("v1-baseline", feats)
            actual = data_sources.synthetic_ground_reading(st, ts, feats["pm25_model"])
            p = Prediction(
                station_id=st, timestamp=ts, predicted_pm25=pred_val, confidence=0.7,
                strategy_version="v1-baseline", agent_version="aeroloop-0.1",
                inputs=feats, source_timestamps={"simulated": ts.isoformat()},
            )
            pid = db.save_prediction(p)
            db.save_reading(GroundReading(
                station_id=st, timestamp=ts, measured_pm25=actual,
                source="synthetic demo (offline stand-in)",
            ))
            err = pred_val - actual
            db.save_error(ErrorRecord(
                prediction_id=pid, station_id=st, timestamp=ts,
                predicted=pred_val, actual=actual, error=err,
                abs_error=abs(err), squared_error=err * err,
            ))
            n += 1
    return {"simulated_pairs": n, "stations": stations, "hours": hours}


@app.get("/strategies")
def strategies():
    return db.get_strategies()


@app.get("/errors")
def errors():
    return db.get_errors()


@app.get("/", response_class=HTMLResponse)
def dashboard():
    html_path = os.path.join(FRONTEND_DIR, "index.html")
    if os.path.exists(html_path):
        with open(html_path) as f:
            return f.read()
    return "<h1>AeroLoop</h1><p>Frontend not found.</p>"


# serve frontend assets
if os.path.isdir(FRONTEND_DIR):
    app.mount("/static", StaticFiles(directory=FRONTEND_DIR), name="static")
