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

from fastapi import FastAPI, Header, HTTPException
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

import agent
import base_anchor
import colocation
import commitments
import data_sources
import db
import evaluation
import prediction
import trust
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
        ("v2-improved", "Model PM2.5 + humidity/wind/precip correction + bias.",
         prediction.STRATEGY_REGISTRY["v2-improved"]["params"]),
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
    readings = {(r["station_id"], r["timestamp"]): r for r in db.get_readings()}
    pairs = []
    for p in db.get_predictions():
        key = (p["station_id"], p["timestamp"])
        if key in readings:
            pairs.append({
                "station_id": p["station_id"],
                "timestamp": p["timestamp"],
                "inputs": json.loads(p["inputs"]),
                "actual": readings[key]["measured_pm25"],
                "source": readings[key].get("source", "unknown"),
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
    pid = db.save_prediction(p, kind="live")
    return {"prediction_id": pid, "prediction": p.model_dump(mode="json")}


@app.post("/ground-truth")
async def ground_truth(station_id: str, prediction_id: int):
    preds = db.get_predictions(station_id)
    target = next((p for p in preds if p["id"] == prediction_id), None)
    if not target:
        raise HTTPException(404, "prediction not found")
    ts = datetime.fromisoformat(target["timestamp"])
    # Real truth first: LAQN hourly PM2.5 where the site measures it and the
    # reading is old enough to be published. Labelled synthetic fallback.
    actual = await data_sources.laqn_reading_for(station_id, ts)
    if actual is not None:
        source = "LAQN (real monitor, ratified)"
    else:
        model_pm25 = (json.loads(target["inputs"]).get("pm25_model") if target["inputs"] else None) or 10.0
        actual = data_sources.synthetic_ground_reading(station_id, ts, model_pm25)
        source = "synthetic (offline stand-in)"
    reading = GroundReading(station_id=station_id, timestamp=ts,
                            measured_pm25=actual, source=source)
    rid = db.save_reading(reading)
    err = target["predicted_pm25"] - actual
    db.save_error(ErrorRecord(
        prediction_id=prediction_id, station_id=station_id, timestamp=ts,
        predicted=target["predicted_pm25"], actual=actual, error=err,
        abs_error=abs(err), squared_error=err * err,
    ))
    return {"reading_id": rid, "measured_pm25": actual, "error": err, "source": source}


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
    result["truth_sources"] = sorted({m["source"] for m in pairs})
    return result


@app.post("/self-improve")
def self_improve():
    pairs = _matched_pairs()
    if len(pairs) < 6:
        raise HTTPException(400, f"need >=6 matched prediction/reading pairs, have {len(pairs)}")
    return agent.run_self_improvement(pairs)


@app.post("/tournament")
def tournament():
    pairs = _matched_pairs()
    if len(pairs) < 6:
        raise HTTPException(400, f"need >=6 matched prediction/reading pairs, have {len(pairs)}")
    return agent.run_tournament(pairs)


@app.get("/tournament/runs")
def tournament_runs(limit: int = 20):
    return db.get_tournament_runs(limit)


@app.get("/tournament/runs/{run_id}")
def tournament_run(run_id: int):
    run = db.get_tournament_run(run_id)
    if run is None:
        raise HTTPException(404, f"tournament run {run_id} not found")
    return run


# ---------------------------------------------------------------------------
# Commitments & anchors — public proof a prediction predates its truth
# ---------------------------------------------------------------------------

def _admin(token: Optional[str]) -> None:
    """Mutating anchor endpoints need X-Admin-Token == ADMIN_TOKEN when set."""
    required = os.getenv("ADMIN_TOKEN")
    if required and token != required:
        raise HTTPException(401, "invalid or missing X-Admin-Token")


@app.get("/commitments/prediction/{prediction_id}")
def commitment(prediction_id: int):
    view = commitments.prediction_commitment(prediction_id)
    if view is None:
        raise HTTPException(404, f"prediction {prediction_id} not found")
    return view


@app.get("/anchors")
def anchors(limit: int = 60):
    return db.get_anchors(min(200, max(1, limit)))


@app.post("/anchors/build")
def anchors_build(date: Optional[str] = None, force: bool = False,
                  x_admin_token: Optional[str] = Header(default=None)):
    _admin(x_admin_token)
    day = date or (datetime.now(timezone.utc) - timedelta(days=1)).date().isoformat()
    built = commitments.build_batch(day, force=force)
    if built.get("status") in ("error", "empty", "exists"):
        status_code = 400 if built.get("status") == "error" else 200
        if built.get("status") == "error":
            raise HTTPException(status_code, built["error"])
        return built

    # each downstream anchor degrades independently
    ots = commitments.stamp_ots(day)
    base = base_anchor.anchor_root(built["root"])
    db.update_anchor(
        built["id"],
        base_status=base["status"], base_network=base["network"],
        base_chain_id=base["chain_id"], base_tx=base["tx_hash"],
        base_block=base["block"], base_block_time=base.get("block_time"),
        base_error=base["error"],
    )
    built["ots"] = ots
    built["base"] = base
    built["explorer_url"] = base.get("explorer_url")
    return built


@app.post("/anchors/upgrade-ots")
def anchors_upgrade(x_admin_token: Optional[str] = Header(default=None)):
    _admin(x_admin_token)
    return {"results": commitments.upgrade_pending_ots()}


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
            pid = db.save_prediction(p, kind="simulated")
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


@app.get("/reference-sites")
def reference_sites(species: Optional[str] = None,
                    qualifying: Optional[bool] = None):
    return db.get_reference_sites(species=species, qualifying=qualifying)


@app.get("/trust")
def trust_report(subject: str = "cams_raw"):
    try:
        return trust.trust_report(subject)
    except ValueError as e:
        raise HTTPException(400, str(e))


@app.get("/colocation")
def colocation_report(species: str = "PM25"):
    return colocation.colocation_report(species)


@app.get("/errors")
def errors():
    return db.get_errors()


@app.get("/wind-field")
async def wind_field():
    """u/v wind over a London grid, grib2json-style records (leaflet-velocity format)."""
    return await data_sources.get_wind_field()


@app.get("/aq-field")
async def aq_field():
    """Modelled PM2.5 + NO2 over a London grid (CAMS via Open-Meteo)."""
    return await data_sources.get_aq_field()


@app.get("/fields-timeline")
async def fields_timeline(hours: int = 24):
    """Per-hour wind + PM2.5 fields for the scene's time scrubber."""
    return await data_sources.get_fields_timeline(min(48, max(1, hours)))


@app.get("/scene-state")
def scene_state():
    """One hydration payload for the Ghost Over London scene."""
    latest_err: Dict[str, Any] = {}
    for e in db.get_errors():
        s = e["station_id"]
        if s not in latest_err or e["timestamp"] > latest_err[s]["timestamp"]:
            latest_err[s] = e
    stations = []
    for sid, (lat, lon) in data_sources.LONDON_STATIONS.items():
        e = latest_err.get(sid)
        stations.append({
            "id": sid, "lat": lat, "lon": lon,
            "latest_pred": e["predicted"] if e else None,
            "latest_actual": e["actual"] if e else None,
            "error": e["error"] if e else None,
            "ts": e["timestamp"] if e else None,
        })
    strats = db.get_strategies()
    return {
        "stations": stations,
        "strategies": [
            {"version": s["version"], "parent": s["parent_version"],
             "kept": not s["version"].endswith("-rejected"),
             "description": s["description"], "created_at": s["created_at"]}
            for s in strats
        ],
        "chapters": [
            {"version": s["version"], "verdict": "rejected" if s["version"].endswith("-rejected") else "kept",
             "t": s["created_at"]}
            for s in strats if not s["version"].startswith("v1") and not s["version"].startswith("v2")
        ],
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }


@app.get("/scene", response_class=HTMLResponse)
def scene():
    html_path = os.path.join(FRONTEND_DIR, "scene.html")
    if os.path.exists(html_path):
        with open(html_path) as f:
            return f.read()
    return HTMLResponse("<h1>scene not found</h1>", status_code=404)


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
