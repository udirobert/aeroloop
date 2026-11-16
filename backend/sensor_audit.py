"""Sensor-vs-reference audit: score co-located sensors against reference truth.

For every `verified_candidate` from the co-location report:
  1. fetch the sensor's hourly history (sensor.community archive CSVs),
  2. save it into sensor_readings,
  3. fetch the same window from its nearest qualifying reference site
     (Luchtmeetnet),
  4. score hourly (sensor, reference) pairs with the trust engine —
     EPA 24-h targets, indicative not certification; drift is our heuristic.

CLI:
    DATABASE_PATH=... python sensor_audit.py \
        --species PM25 --start 2026-11-01 --end 2026-11-09 \
        --out ../submission/evidence/sensor-trust-nl-run1.json
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
from datetime import datetime, timezone
from typing import Any, Dict, List

import colocation
import db
import trust
from sensors import luchtmeetnet as lm
from sensors import sensor_community as sc

REFERENCE_SPACING_S = 1.5  # Luchtmeetnet fair-use: keep well under its limit


async def audit(species: str, start: datetime, end: datetime
                ) -> Dict[str, Any]:
    rep = colocation.colocation_report(species)
    candidates = [r for r in rep["rows"]
                  if r["tier"] == "verified_candidate"]
    sensors = {s["uid"]: s for s in db.get_sensors()}
    lm_client = lm._client()
    sc_client = sc._client()
    results: List[Dict[str, Any]] = []
    try:
        for c in candidates:
            uid, ref_code = c["uid"], c["nearest_reference"]
            meta = sensors[uid]["meta"]
            sid = int(uid.split(":", 1)[1])
            stype = meta.get("sensor_type") or "sds011"

            rows = await asyncio.to_thread(
                sc.fetch_sensor_history, sid, stype, start, end, sc_client)
            for r in rows:
                if r["species"] == species:
                    db.save_sensor_reading(
                        r["uid"], r["timestamp"], r["species"], r["value"],
                        r["flags"])
            subject = {r["timestamp"]: r["value"] for r in rows
                       if r["species"] == species}

            await asyncio.sleep(REFERENCE_SPACING_S)
            reference = await lm.fetch_measurements(
                ref_code, species, start, end, client=lm_client)

            triples = [(ts, sv, reference[ts]) for ts, sv in subject.items()
                       if ts in reference]
            scored = trust.score_triples(triples)
            db.save_sensor_audit({
                "uid": uid, "species": species, "reference": ref_code,
                "distance_m": c["distance_m"], "sensor_type": stype,
                "window_start": start.date().isoformat(),
                "window_end": end.date().isoformat(),
                "sensor_hours": len(subject),
                "reference_hours": len(reference),
                "paired_hours": len(triples), "score": scored,
                "audited_at": datetime.now(timezone.utc)
                .isoformat().replace("+00:00", "Z"),
            })
            results.append({
                "uid": uid, "reference": ref_code,
                "distance_m": c["distance_m"],
                "sensor_type": stype,
                "sensor_hours": len(subject),
                "reference_hours": len(reference),
                "paired_hours": len(triples),
                "score": scored,
            })
            print(f"  {uid} vs {ref_code} ({c['distance_m']} m, {stype}): "
                  f"{len(triples)} paired h, {scored['n_days']} days -> "
                  f"{scored['status']}")
    finally:
        await lm_client.aclose()
        sc_client.close()

    return {
        "generated_at": datetime.now(timezone.utc)
        .isoformat().replace("+00:00", "Z"),
        "species": species,
        "window": f"{start.date().isoformat()}..{end.date().isoformat()}",
        "colocation_max_m": colocation.COLOCATION_MAX_M,
        "sensor_source": "sensor.community archive CSVs (P1=PM10, P2=PM2.5)",
        "reference_source": "RIVM Luchtmeetnet open API",
        "standard": trust.STANDARD,
        "n_candidates": len(candidates),
        "results": results,
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--species", default="PM25", choices=["PM25", "PM10"])
    ap.add_argument("--start", required=True)
    ap.add_argument("--end", required=True)
    ap.add_argument("--out", default=None)
    a = ap.parse_args()
    if not os.getenv("DATABASE_PATH"):
        raise SystemExit("set DATABASE_PATH")
    db.init_db()
    s = datetime.strptime(a.start, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    e = datetime.strptime(a.end, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    rep = asyncio.run(audit(a.species, s, e))
    statuses = {}
    for r in rep["results"]:
        statuses[r["score"]["status"]] = \
            statuses.get(r["score"]["status"], 0) + 1
    print("statuses:", statuses)
    if a.out:
        with open(a.out, "w") as f:
            json.dump(rep, f, indent=2)
        print("written", a.out)


if __name__ == "__main__":
    main()
