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
from typing import Dict, List

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


def _ensure_strategies() -> None:
    import db
    import prediction
    from models import Strategy

    existing = {s["version"] for s in db.get_strategies()}
    for v, desc, params in [
        ("v1-baseline", "Trust CAMS model PM2.5 with light humidity correction.", {}),
        ("v2-improved", "Model PM2.5 + humidity/wind/precip correction + bias.",
         prediction.STRATEGY_REGISTRY["v2-improved"]["params"]),
    ]:
        if v not in existing:
            db.save_strategy(Strategy(version=v, description=desc, params=params,
                                      created_at=datetime.now(timezone.utc)))


async def backfill_site(station_id: str, site_code: str, lat: float, lon: float,
                        start: str, end: str, truth_source: str) -> int:
    """Hindcast one site: CAMS model + weather inputs vs LAQN reference.

    Idempotent per (station_id, timestamp): existing predictions are skipped.
    """
    import db
    import prediction
    from models import ErrorRecord, GroundReading, Prediction

    s = datetime.strptime(start, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    e = datetime.strptime(end, "%Y-%m-%d").replace(tzinfo=timezone.utc)

    truth = await ds.fetch_laqn_pm25(site_code, s, e)
    aq_idx, aq = await _fetch_history(ds.AQ_URL, lat, lon,
                                      "pm2_5,nitrogen_dioxide", start, end)
    wx_idx, wx = await _fetch_history(
        ds.WX_URL, lat, lon,
        "relative_humidity_2m,wind_speed_10m,temperature_2m,precipitation", start, end)

    def at(hourly: dict, idx: dict, key: str, ts: datetime):
        i = idx.get(ts)
        return None if i is None else hourly[key][i]

    done = {p["timestamp"] for p in db.get_predictions(station_id)}

    n = 0
    for raw, value in sorted(truth.items()):
        ts = datetime.strptime(raw[:13], "%Y-%m-%d %H").replace(tzinfo=timezone.utc)
        if ts.isoformat() in done:
            continue
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
        # kind="hindcast": the truth was already published — this row must never
        # read as a pre-truth commitment
        pid = db.save_prediction(Prediction(
            station_id=station_id, timestamp=ts, predicted_pm25=pred,
            confidence=0.7,
            strategy_version="v1-baseline", agent_version="aeroloop-0.1",
            inputs=feats,
            source_timestamps={"cams_model": iso, "laqn_reference": raw},
        ), kind="hindcast")
        db.save_reading(GroundReading(
            station_id=station_id, timestamp=ts, measured_pm25=value,
            source=truth_source,
        ))
        err = pred - value
        db.save_error(ErrorRecord(
            prediction_id=pid, station_id=station_id, timestamp=ts,
            predicted=pred, actual=value, error=err,
            abs_error=abs(err), squared_error=err * err,
        ))
        n += 1
    return n


async def backfill(station: str, start: str, end: str) -> int:
    import db

    db.init_db()
    _ensure_strategies()
    site = ds.LAQN_SITES[station]
    if not site["pm25"]:
        raise SystemExit(f"{station} ({site['code']}) does not publish hourly PM2.5")
    lat, lon = ds.LONDON_STATIONS[station]
    return await backfill_site(
        station, site["code"], lat, lon, start, end,
        truth_source=f"LAQN {site['code']} ratified reference PM2.5")


async def backfill_multi(site_codes: List[str], start: str, end: str) -> Dict[str, int]:
    """Backfill explicit or all qualifying PM2.5 reference sites.

    station_id = "laqn:{code}"; reference coordinates come from
    reference_sites (run reference_sites.py first for --all-qualifying).
    """
    import db

    db.init_db()
    _ensure_strategies()
    refs = {r["code"]: r for r in db.get_reference_sites(species="PM25")
            if r["qualifies"]}
    counts: Dict[str, int] = {}
    for code in site_codes:
        ref = refs.get(code)
        if ref is None:
            print(f"{code}: not a qualifying PM2.5 reference site — skipped")
            continue
        n = await backfill_site(
            f"laqn:{code}", code, ref["lat"], ref["lon"], start, end,
            truth_source=f"LAQN {code} reference PM2.5 (published)")
        counts[code] = n
        print(f"{code}: saved {n} pairs")
        await asyncio.sleep(0.5)  # be polite to Open-Meteo
    return counts


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--station", default="north_kensington")
    ap.add_argument("--site-code", action="append", default=[],
                    help="LAQN site code; repeatable")
    ap.add_argument("--all-qualifying", action="store_true",
                    help="backfill every qualifying PM25 site in reference_sites")
    ap.add_argument("--start", default="2026-11-01")
    ap.add_argument("--end", default="2026-11-09")
    a = ap.parse_args()
    if not os.getenv("DATABASE_PATH"):
        raise SystemExit("set DATABASE_PATH to a dedicated real-reference database")
    import db

    db.init_db()
    if a.all_qualifying or a.site_code:
        if a.all_qualifying:
            codes = [r["code"] for r in db.get_reference_sites(
                species="PM25", qualifying=True)]
        else:
            codes = a.site_code
        counts = asyncio.run(backfill_multi(codes, a.start, a.end))
        print(f"total: {sum(counts.values())} real-reference pairs across "
              f"{len(counts)} sites ({a.start}..{a.end}) "
              f"into {os.environ['DATABASE_PATH']}")
    else:
        n = asyncio.run(backfill(a.station, a.start, a.end))
        print(f"saved {n} real-reference pairs for {a.station} "
              f"({a.start}..{a.end}) into {os.environ['DATABASE_PATH']}")


if __name__ == "__main__":
    main()
