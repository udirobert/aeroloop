"""AeroLoop FastAPI backend: prediction + ground truth + self-improvement."""
from __future__ import annotations

import os
import sys
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List

sys.path.insert(0, os.path.dirname(__file__))

from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import data_sources, db, evaluation, prediction, agent
from .models import GroundReading, Prediction

app = FastAPI(title="AeroLoop", version="0.1.0")

FRONTEND_DIR = os.path.join(os.path.dirname(__file__), "..", "frontend")


@app.on_event("startup")
def _startup():
    db.init_db()
    # seed strategies
    from .models import Strategy

    for v, desc, params in [
        ("v1-baseline", "Trust CAMS model PM2.5 with light humidity correction.", {}),
        ("v2-improved", "Model PM2.5 + humidity/wind/precip correction + bias.", prediction.STRATEGY_REGISTRY["v2-improved"]["params"]),
    ]:
        db.save_strategy(Strategy(version=v, description=desc, params=params, created_at=datetime.utcnow()))


class PredictRequest(BaseModel):
    station_id: str = "bloomsbury"
    strategy_version: str = "v1-baseline"


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
    pred_val = prediction.predict(req.strategy_version, features)
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
    model_pm25 = (target["inputs"] and __import__("json").loads(target["inputs"]).get("pm25_model")) or 10.0
    actual = data_sources.synthetic_ground_reading(station_id, ts, model_pm25 or 10.0)
    reading = GroundReading(station_id=station_id, timestamp=ts, measured_pm25=actual, source="synthetic (offline stand-in)")
    rid = db.save_reading(reading)
    # record error
    err = target["predicted_pm25"] - actual
    from .models import ErrorRecord

    e = ErrorRecord(
        prediction_id=prediction_id,
        station_id=station_id,
        timestamp=ts,
        predicted=target["predicted_pm25"],
        actual=actual,
        error=err,
        abs_error=abs(err),
        squared_error=err * err,
    )
    db.save_error(e)
    return {"reading_id": rid, "measured_pm25": actual, "error": err}


@app.get("/evaluate")
def evaluate(strategy_version: str = "v1-baseline"):
    preds = [p for p in db.get_predictions() if p["strategy_version"] == strategy_version]
    readings = db.get_readings()
    # normalise prediction rows for evaluation
    norm = [
        {"station_id": p["station_id"], "timestamp": p["timestamp"], "predicted_pm25": p["predicted_pm25"]}
        for p in preds
    ]
    return evaluation.evaluate(norm, readings)


@app.post("/self-improve")
def self_improve():
    # build a benchmark from existing v1 predictions + readings
    v1_preds = [p for p in db.get_predictions() if p["strategy_version"] == "v1-baseline"]
    norm = [
        {"station_id": p["station_id"], "timestamp": p["timestamp"],
         "predicted_pm25": p["predicted_pm25"], "inputs": __import__("json").loads(p["inputs"])}
        for p in v1_preds
    ]
    readings = db.get_readings()
    report = agent.run_self_improvement("bloomsbury", norm, readings)
    return report


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
