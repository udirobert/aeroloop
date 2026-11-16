"""Co-location: which low-cost sensors sit near a qualifying reference site.

Tiers:
    verified_candidate  — outdoor sensor within COLOCATION_MAX_M (default
                          500 m) of a qualifying reference site for the
                          species
    no_reference_nearby — outdoor but farther away
    excluded_indoor     — indoor sensor (not comparable to ambient reference)

CLI: `DATABASE_PATH=... python colocation.py --refresh` — refreshes listings
(sensor.community always, Breathe London when BREATHE_LONDON_API_KEY is set)
then prints the summary.
"""
from __future__ import annotations

import argparse
import math
import os
from typing import Any, Dict, List

COLOCATION_MAX_M = float(os.getenv("COLOCATION_MAX_M", "500"))
# default search centre: central London
DEFAULT_LAT, DEFAULT_LON, DEFAULT_KM = 51.5, -0.12, 40.0


def haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    r = 6371000.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    a = (math.sin(dp / 2) ** 2
         + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2)
    return 2 * r * math.asin(math.sqrt(a))


def colocation_report(species: str = "PM25") -> Dict[str, Any]:
    import db
    from sensors import breathe_london

    sensors = db.get_sensors()
    refs = db.get_reference_sites(species=species, qualifying=True)
    tiers = {"verified_candidate": 0, "no_reference_nearby": 0,
             "excluded_indoor": 0}
    rows: List[Dict[str, Any]] = []
    for s in sensors:
        if s["indoor"]:
            tier = "excluded_indoor"
            best = None
        else:
            best = None
            if s["lat"] is not None and s["lon"] is not None:
                for ref in refs:
                    d = haversine_m(s["lat"], s["lon"], ref["lat"], ref["lon"])
                    if best is None or d < best[0]:
                        best = (d, ref)
            if best is not None and best[0] <= COLOCATION_MAX_M:
                tier = "verified_candidate"
            else:
                tier = "no_reference_nearby"
        tiers[tier] += 1
        rows.append({
            "uid": s["uid"], "source": s["source"],
            "nearest_reference": (best[1]["code"] if best else None),
            "distance_m": round(best[0], 1) if best else None,
            "tier": tier,
        })
    out: Dict[str, Any] = {
        "species": species,
        "colocation_max_m": COLOCATION_MAX_M,
        "tiers": tiers,
        "rows": sorted(rows, key=lambda r: (r["tier"] != "verified_candidate",
                                            r["distance_m"] or 1e9)),
    }
    if any(r["source"] == "breathe_london" for r in rows):
        out["attribution"] = breathe_london.ATTRIBUTION
    return out


def refresh(lat: float = DEFAULT_LAT, lon: float = DEFAULT_LON,
            km: float = DEFAULT_KM,
            country: "str | None" = None) -> Dict[str, int]:
    import db
    from sensors import breathe_london, sensor_community

    db.init_db()
    counts = {}
    counts["sensor_community"] = sensor_community.refresh_listings(
        lat, lon, km, country=country)
    counts["breathe_london"] = (breathe_london.refresh_listings()
                              if breathe_london.configured() else 0)
    return counts


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--refresh", action="store_true")
    ap.add_argument("--species", default="PM25")
    ap.add_argument("--lat", type=float, default=DEFAULT_LAT)
    ap.add_argument("--lon", type=float, default=DEFAULT_LON)
    ap.add_argument("--km", type=float, default=DEFAULT_KM)
    ap.add_argument("--country", default=None,
                    help="sensor.community country code (e.g. NL); "
                         "overrides --lat/--lon/--km")
    a = ap.parse_args()
    if not os.getenv("DATABASE_PATH"):
        raise SystemExit("set DATABASE_PATH")
    if a.refresh:
        counts = refresh(a.lat, a.lon, a.km, a.country)
        print("refreshed:", counts)
    import json
    rep = colocation_report(a.species)
    print(json.dumps({"tiers": rep["tiers"],
                      "rows": rep["rows"][:50]}, indent=2))


if __name__ == "__main__":
    main()
