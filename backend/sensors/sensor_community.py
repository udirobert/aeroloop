"""sensor.community adapter.

Listings: GET https://data.sensor.community/airrohr/v1/filter/area={lat},{lon},{km}
or filter/country={cc} for a whole country (e.g. NL).
History:  GET https://archive.sensor.community/{date}/{date}_{type}_sensor_{id}.csv
(semicolon CSV, ~2.5-min samples, UTC timestamps).
Requires a User-Agent header (env SENSOR_COMMUNITY_UA).

PM columns are named the same across sensor types: P1 = PM10, P2 = PM2.5
(SPS30 also exposes P0 = PM1 and P4 = PM4, which we ignore).
"""
from __future__ import annotations

import csv
import io
import os
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

import httpx

AREA_URL = "https://data.sensor.community/airrohr/v1/filter/area={lat},{lon},{km}"
COUNTRY_URL = "https://data.sensor.community/airrohr/v1/filter/country={cc}"
ARCHIVE_URL = ("https://archive.sensor.community/{date}/"
               "{date}_{stype}_sensor_{sid}.csv")
USER_AGENT = os.getenv(
    "SENSOR_COMMUNITY_UA",
    "AeroLoop/0.1 (+https://github.com/udirobert/aeroloop)",
)
PM_TYPES = {"P1", "P2"}  # P1 = PM10, P2 = PM2.5
SPECIES_COLS = {"P1": "PM10", "P2": "PM25"}


def _client() -> httpx.Client:
    return httpx.Client(timeout=60, headers={"User-Agent": USER_AGENT})


def _norm_row(row: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    values = {v.get("value_type") for v in row.get("sensordatavalues", [])}
    if not values & PM_TYPES:
        return None
    loc = row.get("location") or {}
    sensor = row.get("sensor") or {}
    return {
        "uid": f"sc:{sensor.get('id')}",
        "source": "sensor_community",
        "lat": float(loc["latitude"]) if loc.get("latitude") else None,
        "lon": float(loc["longitude"]) if loc.get("longitude") else None,
        "indoor": int(bool(loc.get("indoor"))),
        "meta": {
            "sensor_type": (sensor.get("sensor_type") or {}).get("name"),
            "value_types": sorted(values & PM_TYPES),
        },
    }


def list_pm_sensors(lat: float, lon: float, km: float,
                    client: Optional[httpx.Client] = None) -> Dict[str, Any]:
    """PM-capable sensors within km of (lat, lon), indoor flag kept."""
    own = client is None
    client = client or _client()
    try:
        r = client.get(AREA_URL.format(lat=lat, lon=lon, km=km))
        r.raise_for_status()
        sensors = [s for s in (_norm_row(r_) for r_ in r.json()) if s]
        return {"status": "ok", "sensors": sensors}
    finally:
        if own:
            client.close()


def list_country_pm_sensors(country: str,
                            client: Optional[httpx.Client] = None
                            ) -> Dict[str, Any]:
    """PM-capable sensors for a whole country (e.g. "NL"), indoor flag kept."""
    own = client is None
    client = client or _client()
    try:
        r = client.get(COUNTRY_URL.format(cc=country))
        r.raise_for_status()
        sensors = [s for s in (_norm_row(r_) for r_ in r.json()) if s]
        return {"status": "ok", "sensors": sensors}
    finally:
        if own:
            client.close()


def refresh_listings(lat: float = 51.5, lon: float = -0.12, km: float = 40,
                     country: Optional[str] = None,
                     client: Optional[httpx.Client] = None) -> int:
    """List sensors (country-wide if `country` set, else around a point)
    and upsert into the sensors table."""
    import db

    res = (list_country_pm_sensors(country, client=client) if country
           else list_pm_sensors(lat, lon, km, client=client))
    if res["status"] != "ok":
        return 0
    from datetime import datetime, timezone
    now = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    for s in res["sensors"]:
        s["listed_at"] = now
        db.upsert_sensor(s)
    return len(res["sensors"])


def fetch_sensor_history(sensor_id: int, sensor_type: str,
                         start: datetime, end: datetime,
                         client: Optional[httpx.Client] = None
                         ) -> List[Dict[str, Any]]:
    """Hourly PM10/PM2.5 means for one sensor over [start, end] (inclusive days).

    Pulls the daily archive CSVs (sub-hourly samples, UTC), averages each
    calendar hour, and returns rows shaped like breathe_london.sensor_data:
    [{"uid","timestamp","species","value","flags"}] with timestamp
    "YYYY-MM-DD HH:00:00". Missing days/files are skipped silently.
    """
    own = client is None
    client = client or _client()
    uid = f"sc:{sensor_id}"
    buckets: Dict[tuple, List[float]] = {}
    days_ok: List[str] = []
    try:
        day = start.date()
        while day <= end.date():
            url = ARCHIVE_URL.format(
                date=day.isoformat(),
                stype=sensor_type.lower(), sid=sensor_id)
            try:
                r = client.get(url)
            except httpx.HTTPError:
                r = None
            if r is not None and r.status_code == 200:
                days_ok.append(day.isoformat())
                for row in csv.DictReader(io.StringIO(r.text),
                                          delimiter=";"):
                    hour = (row.get("timestamp") or "")[:13]
                    if not hour:
                        continue
                    for col, species in SPECIES_COLS.items():
                        raw = row.get(col)
                        if raw in (None, ""):
                            continue
                        try:
                            v = float(raw)
                        except ValueError:
                            continue
                        buckets.setdefault((hour, species), []).append(v)
            day += timedelta(days=1)
    finally:
        if own:
            client.close()
    out: List[Dict[str, Any]] = []
    for (hour, species), vals in sorted(buckets.items()):
        out.append({
            "uid": uid,
            "timestamp": hour.replace("T", " ") + ":00:00",
            "species": species,
            "value": sum(vals) / len(vals),
            "flags": {"source": "archive.sensor.community",
                      "n_samples": len(vals),
                      "sensor_type": sensor_type,
                      "days_fetched": len(days_ok)},
        })
    return out
