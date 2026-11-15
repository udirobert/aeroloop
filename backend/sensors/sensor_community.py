"""sensor.community adapter — listing only (no history fetch yet).

GET https://data.sensor.community/airrohr/v1/filter/area={lat},{lon},{km}
requires a User-Agent header (env SENSOR_COMMUNITY_UA).
"""
from __future__ import annotations

import os
from typing import Any, Dict, Optional

import httpx

AREA_URL = "https://data.sensor.community/airrohr/v1/filter/area={lat},{lon},{km}"
USER_AGENT = os.getenv(
    "SENSOR_COMMUNITY_UA",
    "AeroLoop/0.1 (+https://github.com/udirobert/aeroloop)",
)
PM_TYPES = {"P1", "P2"}  # P1 = PM10, P2 = PM2.5


def _client() -> httpx.Client:
    return httpx.Client(timeout=30, headers={"User-Agent": USER_AGENT})


def list_pm_sensors(lat: float, lon: float, km: float,
                    client: Optional[httpx.Client] = None) -> Dict[str, Any]:
    """PM-capable sensors within km of (lat, lon), indoor flag kept."""
    own = client is None
    client = client or _client()
    try:
        r = client.get(AREA_URL.format(lat=lat, lon=lon, km=km))
        r.raise_for_status()
        sensors = []
        for row in r.json():
            values = {v.get("value_type")
                      for v in row.get("sensordatavalues", [])}
            if not values & PM_TYPES:
                continue
            loc = row.get("location") or {}
            sensor = row.get("sensor") or {}
            sensors.append({
                "uid": f"sc:{sensor.get('id')}",
                "source": "sensor_community",
                "lat": float(loc["latitude"]) if loc.get("latitude") else None,
                "lon": float(loc["longitude"]) if loc.get("longitude") else None,
                "indoor": int(bool(loc.get("indoor"))),
                "meta": {
                    "sensor_type": (sensor.get("sensor_type") or {}).get("name"),
                    "value_types": sorted(values & PM_TYPES),
                },
            })
        return {"status": "ok", "sensors": sensors}
    finally:
        if own:
            client.close()


def refresh_listings(lat: float = 51.5, lon: float = -0.12, km: float = 40,
                     client: Optional[httpx.Client] = None) -> int:
    """List sensors around a point and upsert into the sensors table."""
    import db

    res = list_pm_sensors(lat, lon, km, client=client)
    if res["status"] != "ok":
        return 0
    from datetime import datetime, timezone
    now = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    for s in res["sensors"]:
        s["listed_at"] = now
        db.upsert_sensor(s)
    return len(res["sensors"])
