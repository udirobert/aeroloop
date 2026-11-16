"""RIVM Luchtmeetnet adapter — the Dutch national reference network.

GET https://api.luchtmeetnet.nl/open_api/... — public, no API key, fair-use
policy. Responses are paginated JSON. Windows longer than ~5 days 302-redirect
to iq.luchtmeetnet.nl (the bulk query host) — clients must follow redirects.
Species formulas match the LAQN convention: PM10, PM25.

Same qualification rule as LAQN: a station's `components` list is metadata;
sites qualify by probing measurements, never by the list.
"""
from __future__ import annotations

import os
from datetime import datetime
from typing import Any, Dict, List, Optional

import httpx

BASE_URL = os.getenv(
    "LUCHTMEETNET_BASE_URL", "https://api.luchtmeetnet.nl/open_api")
MAX_PAGES = 100  # safety stop; stations list is ~5 pages today
SPECIES = ("PM25", "PM10")  # formula names as served by the API


def _client() -> httpx.AsyncClient:
    return httpx.AsyncClient(timeout=30, follow_redirects=True)


async def _paged(path: str, params: Dict[str, Any],
                 client: httpx.AsyncClient) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    page = 1
    while True:
        r = await client.get(f"{BASE_URL}{path}",
                             params={**params, "page": page})
        r.raise_for_status()
        d = r.json()
        out.extend(d.get("data") or [])
        if page >= d.get("pagination", {}).get("last_page", 1):
            return out
        page += 1
        if page > MAX_PAGES:
            return out


async def list_stations(client: Optional[httpx.AsyncClient] = None
                        ) -> List[Dict[str, Any]]:
    """All stations: [{"number": "NL49012", "location": "..."}, ...]."""
    own = client is None
    client = client or _client()
    try:
        return await _paged("/stations", {}, client)
    finally:
        if own:
            await client.aclose()


async def fetch_station(number: str,
                        client: Optional[httpx.AsyncClient] = None
                        ) -> Dict[str, Any]:
    """Normalised station detail: code, name, lat/lon, site type, components.

    `components` is the station's claimed species list — metadata only.
    """
    own = client is None
    client = client or _client()
    try:
        r = await client.get(f"{BASE_URL}/stations/{number}")
        r.raise_for_status()
        d = r.json()["data"]
        lon, lat = (d.get("geometry") or {}).get("coordinates") or [None, None]
        return {
            "code": number,
            "name": d.get("location"),
            "lat": float(lat) if lat is not None else None,
            "lon": float(lon) if lon is not None else None,
            "site_type": d.get("type"),
            "components": d.get("components") or [],
            "organisation": d.get("organisation"),
            "municipality": d.get("municipality"),
        }
    finally:
        if own:
            await client.aclose()


async def fetch_measurements(number: str, formula: str,
                             start: datetime, end: datetime,
                             client: Optional[httpx.AsyncClient] = None
                             ) -> Dict[str, float]:
    """Hourly readings (µg/m³) for a station+formula over [start, end].

    Returns {"YYYY-MM-DD HH:00:00": value} keyed on the hour the measurement
    period STARTS (timestamp_measured_start), matching the LAQN convention.
    Rows with a null value are gaps in the record and are skipped.
    """
    own = client is None
    client = client or _client()
    try:
        rows = await _paged("/measurements", {
            "station_number": number, "formula": formula,
            "start": start.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "end": end.strftime("%Y-%m-%dT%H:%M:%SZ"),
        }, client)
    finally:
        if own:
            await client.aclose()
    out: Dict[str, float] = {}
    for row in rows:
        t, v = row.get("timestamp_measured_start"), row.get("value")
        if v is None or not t:
            continue
        try:
            out[t[:13].replace("T", " ") + ":00:00"] = float(v)
        except (TypeError, ValueError):
            pass
    return out
