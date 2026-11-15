"""Backfill a real-reference audit: LAQN ratified PM2.5 vs historical CAMS inputs.

Run against a dedicated DATABASE_PATH so real and synthetic audits never share a
table. Predictions are computed from model + weather inputs only; the reference
value is written afterwards and never feeds the prediction.

    DATABASE_PATH=../data/aeroloop-laqn.db python backfill_laqn.py \
        --start 2026-11-01 --end 2026-11-09

This is a hindcast over already-ratified hours, not a live pre-registered
prediction: the "committed before truth existed" guarantee does not apply here.
"""
from __future__ import annotations

import argparse
import asyncio
import os
from datetime import datetime, timezone

import httpx

import data_sources as ds


def _hour_key(s: str) -> datetime:
    return datetime.strptime(s[:13], "%Y-%m-%dT%H").replace(tzinfo=timezone.utc)


async def _fetch_history(url: str, lat: float, lon: float, hourly: str,
                         start: str, end: str) -> dict:
    async with httpx.AsyncClient(timeout=60) as client:
        r = await client.get(url, params={
            "latitude": lat, "longitude": lon, "hourly": hourly,
            "start_date": start, "end_date": end,
        })
        r.raise_for_status()
        h = r.json()["hourly"]
    return {_hour_key(t): i for i, t in enumerate(h["time"])}, h


async def backfill(station: str, start: str, end: str) -> int:
    import db
    import prediction
    from models import ErrorRecord, GroundReading, Prediction, Strategy

    db.init_db()
    existing = {s["version"] for s in db.get_strategies()}
    for v, desc, params in [
        ("v1-baseline", "Trust CAMS model PM2.5 with light humidity correction.", {}),
        ("v2-improved", "Model PM2.5 + humidity/wind/precip correction + bias.",
         prediction.STRATEGY_REGISTRY["v2-improved"]["params"]),
    ]:
        if v not in existing:
            db.save_strategy(Strategy(version=v, description=desc, params=params,
                                      created_at=datetime.now(timezone.utc)))

    site = ds.LAQN_SITES[station]
    if not site["pm25"]:
        raise SystemExit(f"{station} ({site['code']}) does not publish hourly PM2.5")
    lat, lon = ds.LONDON_STATIONS[station]
    s = datetime.strptime(start, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    e = datetime.strptime(end, "%Y-%m-%d").replace(tzinfo=timezone.utc)

    truth = await ds.fetch_laqn_pm25(site["code"], s, e)
    aq_idx, aq = await _fetch_history(ds.AQ_URL, lat, lon,
                                      "pm2_5,nitrogen_dioxide", start, end)
    wx_idx, wx = await _fetch_history(
        ds.WX_URL, lat, lon,
        "relative_humidity_2m,wind_speed_10m,temperature_2m,precipitation", start, end)

    def at(hourly: dict, idx: dict, key: str, ts: datetime):
        i = idx.get(ts)
        return None if i is None else hourly[key][i]

    n = 0
    for raw, value in sorted(truth.items()):
        ts = datetime.strptime(raw[:13], "%Y-%m-%d %H").replace(tzinfo=timezone.utc)
        pm = at(aq, aq_idx, "pm2_5", ts)
        hum = at(wx, wx_idx, "relative_humidity_2m", ts)
        if pm is None or hum is None:
            continue
        feats = {
            "pm25_model": pm,
            "no2_model": at(aq, aq_idx, "nitrogen_dioxide", ts),
            "humidity": hum,
            "wind_speed": at(wx, wx_idx, "wind_speed_10m", ts),
            "temperature": at(wx, wx_idx, "temperature_2m", ts),
            "precipitation": at(wx, wx_idx, "precipitation", ts),
            "timestamp": ts.isoformat(),
        }
        pred = prediction.predict("v1-baseline", feats)
        iso = ts.isoformat()
        # kind="hindcast": the truth was already ratified — this row must never
        # read as a pre-truth commitment
        pid = db.save_prediction(Prediction(
            station_id=station, timestamp=ts, predicted_pm25=pred, confidence=0.7,
            strategy_version="v1-baseline", agent_version="aeroloop-0.1",
            inputs=feats,
            source_timestamps={"cams_model": iso, "laqn_reference": raw},
        ), kind="hindcast")
        db.save_reading(GroundReading(
            station_id=station, timestamp=ts, measured_pm25=value,
            source=f"LAQN {site['code']} ratified reference PM2.5",
        ))
        err = pred - value
        db.save_error(ErrorRecord(
            prediction_id=pid, station_id=station, timestamp=ts,
            predicted=pred, actual=value, error=err,
            abs_error=abs(err), squared_error=err * err,
        ))
        n += 1
    return n


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--station", default="north_kensington")
    ap.add_argument("--start", default="2026-11-01")
    ap.add_argument("--end", default="2026-11-09")
    a = ap.parse_args()
    if not os.getenv("DATABASE_PATH"):
        raise SystemExit("set DATABASE_PATH to a dedicated real-reference database")
    n = asyncio.run(backfill(a.station, a.start, a.end))
    print(f"saved {n} real-reference pairs for {a.station} "
          f"({a.start}..{a.end}) into {os.environ['DATABASE_PATH']}")


if __name__ == "__main__":
    main()
