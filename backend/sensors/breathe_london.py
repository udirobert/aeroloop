"""Breathe London API adapter.

Docs: https://www.breathelondon.org/developers
Data is OGL v3 — anything returning or displaying it must carry ATTRIBUTION.
Env: BREATHE_LONDON_API_KEY (required), BREATHE_LONDON_BASE_URL.
"""
from __future__ import annotations

import os
from typing import Any, Dict, Optional

import httpx

BASE_URL = os.getenv(
    "BREATHE_LONDON_BASE_URL",
    "https://breathe-london-7x54d7qf.ew.gateway.dev",
)
ATTRIBUTION = ("Contains Breathe London data licensed under the "
               "Open Government License v3.0 (https://www.breathelondon.org/)")


def _client() -> httpx.Client:
    key = os.getenv("BREATHE_LONDON_API_KEY")
    return httpx.Client(timeout=30, headers={"X-API-KEY": key or ""})


def configured() -> bool:
    return bool(os.getenv("BREATHE_LONDON_API_KEY"))


def list_sensors(lat: Optional[float] = None, lon: Optional[float] = None,
                 radius_km: Optional[float] = None,
                 client: Optional[httpx.Client] = None) -> Dict[str, Any]:
    """Normalised sensor listings, or {"status": "not_configured"}."""
    if not configured():
        return {"status": "not_configured", "sensors": []}
    params: Dict[str, Any] = {}
    if lat is not None and lon is not None:
        params["Latitude"] = lat
        params["Longitude"] = lon
        if radius_km is not None:
            params["RadiusKM"] = radius_km
    own = client is None
    client = client or _client()
    try:
        r = client.get(f"{BASE_URL}/ListSensors", params=params)
        r.raise_for_status()
        sensors = [_norm_sensor(s) for s in r.json()]
        return {"status": "ok", "sensors": sensors,
                "attribution": ATTRIBUTION}
    finally:
        if own:
            client.close()


def _norm_sensor(s: Dict[str, Any]) -> Dict[str, Any]:
    meta = {k: s.get(k) for k in (
        "SiteName", "DeviceCode", "InstallationCode", "Borough",
        "SiteClassification", "SensorHeightAboveGround", "DistanceToKerb",
        "SponsorName", "SiteLocationType", "StartDate", "EndDate")}
    return {
        "uid": f"bl:{s.get('SiteCode')}",
        "source": "breathe_london",
        "lat": float(s["Latitude"]) if s.get("Latitude") else None,
        "lon": float(s["Longitude"]) if s.get("Longitude") else None,
        "indoor": 0,
        "meta": meta,
    }


def sensor_data(site_code: str, start: str, end: str, species: str = "PM25",
                client: Optional[httpx.Client] = None) -> Dict[str, Any]:
    """Normalised hourly rows for one SiteCode.

    start/end are ISO date-times. Rows keep RatificationStatus/Source/Duration
    in flags; value is ScaledValue (ug.m-3).
    """
    if not configured():
        return {"status": "not_configured", "readings": []}
    own = client is None
    client = client or _client()
    try:
        r = client.get(f"{BASE_URL}/SensorData", params={
            "SiteCode": site_code, "Species": species,
            "startTime": start, "endTime": end,
        })
        r.raise_for_status()
        rows = r.json()
        readings = [{
            "uid": f"bl:{row['SiteCode']}",
            "timestamp": row["DateTime"],
            "species": row.get("Species", species),
            "value": row.get("ScaledValue"),
            "flags": {
                "ratification_status": row.get("RatificationStatus"),
                "source": row.get("Source"),
                "duration": row.get("Duration"),
                "sensor_contract": row.get("SensorContract"),
            },
        } for row in rows]
        return {"status": "ok", "readings": readings,
                "attribution": ATTRIBUTION}
    finally:
        if own:
            client.close()


def refresh_listings(client: Optional[httpx.Client] = None) -> int:
    """List all sensors and upsert into the sensors table."""
    import db

    res = list_sensors(client=client)
    if res["status"] != "ok":
        return 0
    from datetime import datetime, timezone
    now = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    for s in res["sensors"]:
        s["listed_at"] = now
        db.upsert_sensor(s)
    return len(res["sensors"])
