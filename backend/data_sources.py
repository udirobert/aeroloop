"""Data ingestion: Open-Meteo Air Quality + weather for London monitoring stations.

Scientific notes:
- Open-Meteo Air Quality provides CAMS-based PM2.5/NO2 forecasts (model output,
  not measurements). Resolution ~11km.
- Weather: humidity, wind, temperature, precipitation.
- Ground truth comes from DEFRA AURN (not wired in v1; a synthetic ground
  reading is generated for the demo loop so the self-improvement cycle is
  runnable offline). Swap in real AURN data for production.
"""
from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
from typing import Dict

import httpx

AQ_URL = os.getenv("OPEN_METEO_AQ_URL", "https://air-quality-api.open-meteo.com/v1/air-quality")
WX_URL = os.getenv("OPEN_METEO_WEATHER_URL", "https://api.open-meteo.com/v1/forecast")

# A small set of London monitoring-station proxies (lat/lon).
LONDON_STATIONS = {
    "bloomsbury": (51.5225, -0.1310),
    "marylebone": (51.5226, -0.1546),
    "north_kensington": (51.5210, -0.2134),
    "westminster": (51.4975, -0.1357),
}

# LondonAir (LAQN) site codes + whether the site publishes PM2.5.
# Verified against api.erg.ic.ac.uk 2026-11-05: only KC1 reports hourly PM25.
# LAQN readings are QC'd before publication — they lag ~5 days behind realtime,
# which suits the project's delayed-truth mechanic: predict now, truth later.
LAQN_URL = os.getenv("LAQN_URL", "http://api.erg.ic.ac.uk/AirQuality")
LAQN_SITES = {
    "bloomsbury": {"code": "BL0", "pm25": False},
    "marylebone": {"code": "MY1", "pm25": False},
    "north_kensington": {"code": "KC1", "pm25": True},
    "westminster": {"code": "VS1", "pm25": False},
}
LAQN_MIN_LAG_DAYS = 5  # readings younger than this are unlikely to be published


async def fetch_laqn_pm25(site_code: str, start: datetime, end: datetime) -> Dict[str, float]:
    """Hourly PM2.5 readings (µg/m³) for a LAQN site over [start, end].

    Returns {iso_hour: value}. Empty when the site doesn't measure PM2.5 or
    the readings aren't published yet (LAQN ratification lag).
    """
    url = (f"{LAQN_URL}/Data/Site/SiteCode={site_code}"
           f"/StartDate={start:%Y-%m-%d}/EndDate={end:%Y-%m-%d}/Json")
    async with httpx.AsyncClient(timeout=30) as client:
        r = await client.get(url)
        r.raise_for_status()
        d = r.json()
    out: Dict[str, float] = {}
    for row in d.get("AirQualityData", {}).get("Data", []) or []:
        if row.get("@SpeciesCode") != "PM25":
            continue
        v = row.get("@Value")
        t = row.get("@MeasurementDateGMT")
        if v in (None, "") or not t:
            continue
        try:
            out[t] = float(v)
        except ValueError:
            pass
    return out


async def laqn_reading_for(station_id: str, ts: datetime) -> "float | None":
    """Real LAQN PM2.5 for a station+hour if the site measures it and the
    reading is old enough to have been ratified/published (~5d lag)."""
    site = LAQN_SITES.get(station_id)
    if not site or not site["pm25"]:
        return None
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)
    if (datetime.now(timezone.utc) - ts).days < LAQN_MIN_LAG_DAYS:
        return None  # too recent — LAQN hasn't ratified it yet
    try:
        start, end = ts - timedelta(hours=6), ts + timedelta(hours=6)
        readings = await fetch_laqn_pm25(site["code"], start, end)
    except Exception:
        return None
    # match the prediction's hour (LAQN stamps "YYYY-MM-DD HH:00:00" GMT)
    key = ts.strftime("%Y-%m-%d %H:00:00")
    if key in readings:
        return readings[key]
    # nearest hour within ±3h as a tolerance
    for hh in (1, -1, 2, -2, 3, -3):
        k = (ts + timedelta(hours=hh)).strftime("%Y-%m-%d %H:00:00")
        if k in readings:
            return readings[k]
    return None


async def fetch_air_quality(lat: float, lon: float, hours: int = 24) -> Dict:
    """Fetch PM2.5 + NO2 from Open-Meteo Air Quality (CAMS model)."""
    params = {
        "latitude": lat,
        "longitude": lon,
        "hourly": "pm2_5,nitrogen_dioxide",
        "forecast_days": 1,
        "past_days": 1,
    }
    async with httpx.AsyncClient(timeout=30) as client:
        r = await client.get(AQ_URL, params=params)
        r.raise_for_status()
        return r.json()


async def fetch_weather(lat: float, lon: float) -> Dict:
    """Fetch humidity, wind, temperature, precipitation."""
    params = {
        "latitude": lat,
        "longitude": lon,
        "hourly": "relative_humidity_2m,wind_speed_10m,temperature_2m,precipitation",
        "forecast_days": 1,
        "past_days": 1,
    }
    async with httpx.AsyncClient(timeout=30) as client:
        r = await client.get(WX_URL, params=params)
        r.raise_for_status()
        return r.json()


# --- Gridded fields for the Ghost Over London scene -------------------------
# Inner-London bbox; ~1.3km spacing is plenty for haze + wind fields.
LONDON_BBOX = {"south": 51.45, "west": -0.28, "north": 51.56, "east": -0.08}
GRID_NX, GRID_NY = 20, 14

_CACHE_DIR = os.getenv(
    "AEROLOOP_CACHE_DIR",
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "data", "cache"),
)
FIELD_CACHE_TTL_S = 900  # 15 min
_field_cache: Dict[str, Dict] = {}


def _grid_points() -> list:
    """Grid points row-major: north→south rows, west→east within a row."""
    lats = [LONDON_BBOX["north"] - i * (LONDON_BBOX["north"] - LONDON_BBOX["south"]) / (GRID_NY - 1)
            for i in range(GRID_NY)]
    lons = [LONDON_BBOX["west"] + j * (LONDON_BBOX["east"] - LONDON_BBOX["west"]) / (GRID_NX - 1)
            for j in range(GRID_NX)]
    return [(la, lo) for la in lats for lo in lons]


async def _fetch_multi(url: str, hourly: str) -> list:
    """One Open-Meteo call for the whole grid (pairwise lat/lon lists)."""
    pts = _grid_points()
    params = {
        "latitude": ",".join(f"{p[0]:.4f}" for p in pts),
        "longitude": ",".join(f"{p[1]:.4f}" for p in pts),
        "hourly": hourly,
        "forecast_days": 1,
        "timezone": "UTC",
    }
    async with httpx.AsyncClient(timeout=60) as client:
        r = await client.get(url, params=params)
        r.raise_for_status()
        return r.json()


def _latest_idx(times: list) -> int:
    """Index of the hourly row closest to now."""
    now = datetime.now(timezone.utc)
    best, best_d = 0, float("inf")
    for i, t in enumerate(times):
        try:
            dt = datetime.fromisoformat(t)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
        except Exception:
            continue
        d = abs((dt - now).total_seconds())
        if d < best_d:
            best, best_d = i, d
    return best


def _cache_path(name: str) -> str:
    return os.path.join(_CACHE_DIR, f"{name}.json")


def _save_cached(name: str, payload: Dict) -> None:
    try:
        import json as _json
        os.makedirs(_CACHE_DIR, exist_ok=True)
        with open(_cache_path(name), "w") as f:
            _json.dump(payload, f)
    except Exception:
        pass


def _load_cached(name: str):
    try:
        import json as _json
        with open(_cache_path(name)) as f:
            return _json.load(f)
    except Exception:
        return None


async def _with_cache(name: str, fetcher, fallback) -> Dict:
    """Shared fetch→mem-cache→disk-cache→synthetic-fallback plumbing."""
    cached = _field_cache.get(name)
    if cached and (datetime.now(timezone.utc) - cached["ts"]).total_seconds() < FIELD_CACHE_TTL_S:
        return cached["payload"]
    try:
        payload = await fetcher()
        payload["source"] = "open-meteo (live)"
        _save_cached(name, payload)
    except Exception:
        disk = _load_cached(name)
        if disk:
            disk["source"] = "cached snapshot (offline)"
            payload = disk
        else:
            payload = fallback()
            payload["source"] = "synthetic field (offline stand-in)"
    _field_cache[name] = {"ts": datetime.now(timezone.utc), "payload": payload}
    return payload


def _uv(speed_ms: float, dir_deg: float) -> tuple:
    """Meteorological convention: direction is where the wind comes FROM."""
    import math
    rad = math.radians(dir_deg or 0.0)
    return -speed_ms * math.sin(rad), -speed_ms * math.cos(rad)


def _record(param_no: int, data: list) -> Dict:
    """grib2json-style record — the format leaflet-velocity consumes."""
    return {"header": {
        "parameterCategory": 2, "parameterNumber": param_no,
        "nx": GRID_NX, "ny": GRID_NY,
        "lo1": LONDON_BBOX["west"], "la1": LONDON_BBOX["north"],
        "lo2": LONDON_BBOX["east"], "la2": LONDON_BBOX["south"],
        "dx": (LONDON_BBOX["east"] - LONDON_BBOX["west"]) / (GRID_NX - 1),
        "dy": (LONDON_BBOX["north"] - LONDON_BBOX["south"]) / (GRID_NY - 1),
        "refTime": datetime.now(timezone.utc).isoformat(),
    }, "data": data}


async def fetch_wind_field() -> Dict:
    """u/v wind components over the London grid, latest hour."""
    rows = await _fetch_multi(WX_URL, "wind_speed_10m,wind_direction_10m")
    u = [0.0] * (GRID_NX * GRID_NY)
    v = [0.0] * (GRID_NX * GRID_NY)
    for i, loc in enumerate(rows):
        h = loc.get("hourly", {})
        idx = _latest_idx(h.get("time") or [])
        sp = (h.get("wind_speed_10m") or [0.0])[idx] or 0.0
        dr = (h.get("wind_direction_10m") or [0.0])[idx] or 0.0
        u[i], v[i] = _uv(sp, dr)
    return {"records": [_record(2, u), _record(3, v)],
            "bbox": LONDON_BBOX, "nx": GRID_NX, "ny": GRID_NY}


async def fetch_aq_field() -> Dict:
    """PM2.5 + NO2 over the London grid, latest hour (CAMS modelled)."""
    rows = await _fetch_multi(AQ_URL, "pm2_5,nitrogen_dioxide")
    pm = [0.0] * (GRID_NX * GRID_NY)
    no2 = [0.0] * (GRID_NX * GRID_NY)
    ts = None
    for i, loc in enumerate(rows):
        h = loc.get("hourly", {})
        times = h.get("time") or []
        idx = _latest_idx(times)
        pm[i] = (h.get("pm2_5") or [0.0])[idx] or 0.0
        no2[i] = (h.get("nitrogen_dioxide") or [0.0])[idx] or 0.0
        if times:
            ts = times[idx]
    return {"nx": GRID_NX, "ny": GRID_NY, "bbox": LONDON_BBOX,
            "pm25": pm, "no2": no2, "time": ts,
            "kind": "modelled (CAMS via Open-Meteo)"}


def _synthetic_wind_field() -> Dict:
    """Deterministic gentle westerly flow for fully-offline first run."""
    import math
    rng_pts = _grid_points()
    u, v = [], []
    for la, lo in rng_pts:
        # mostly westerly (u<0? no — westerly wind blows eastward: u>0)
        uu = 4.5 + 1.5 * math.sin(la * 40) + 0.8 * math.cos(lo * 60)
        vv = 0.8 * math.sin(lo * 50)
        u.append(round(uu, 3))
        v.append(round(vv, 3))
    return {"records": [_record(2, u), _record(3, v)],
            "bbox": LONDON_BBOX, "nx": GRID_NX, "ny": GRID_NY}


def _synthetic_aq_field() -> Dict:
    """Smooth PM2.5 blob over the city centre for fully-offline first run."""
    import math
    import random
    rng = random.Random(7)
    cx = (LONDON_BBOX["east"] + LONDON_BBOX["west"]) / 2 - 0.02
    cy = (LONDON_BBOX["north"] + LONDON_BBOX["south"]) / 2
    pm, no2 = [], []
    for la, lo in _grid_points():
        d = math.hypot((la - cy) * 2.2, (lo - cx) * 1.2)
        base = 6.0 + 16.0 * math.exp(-d * d * 60)
        val = max(0.0, base + rng.uniform(-1.5, 1.5))
        pm.append(round(val, 2))
        no2.append(round(val * 2.4 + 8, 2))
    return {"nx": GRID_NX, "ny": GRID_NY, "bbox": LONDON_BBOX,
            "pm25": pm, "no2": no2, "time": datetime.now(timezone.utc).isoformat(),
            "kind": "synthetic field (offline stand-in)"}


async def get_wind_field() -> Dict:
    return await _with_cache("wind-field", fetch_wind_field, _synthetic_wind_field)


async def get_aq_field() -> Dict:
    return await _with_cache("aq-field", fetch_aq_field, _synthetic_aq_field)


def synthetic_ground_reading(station_id: str, ts: datetime, model_pm25: float) -> float:
    """Offline stand-in for a DEFRA AURN ground measurement.

    Adds realistic noise + a systematic bias so the self-improvement loop has
    something to learn. Replace with real AURN data in production.
    """
    import hashlib
    import random

    # stable hash — Python's hash() is randomised per process
    seed = int(hashlib.md5(f"{station_id}|{ts.isoformat()}".encode()).hexdigest()[:8], 16)
    rng = random.Random(seed)
    # ground truth tends to be a bit higher than model (typical urban bias)
    noise = rng.gauss(0, 3.0)
    bias = 4.0 if station_id in ("marylebone", "bloomsbury") else 1.5
    return max(0.0, model_pm25 + bias + noise)


def align_latest(aq: Dict, wx: Dict) -> Dict:
    """Pull the most recent hourly row from both payloads into one feature dict."""
    aq_h = aq.get("hourly", {})
    wx_h = wx.get("hourly", {})
    idx = -1  # latest available
    return {
        "pm25_model": (aq_h.get("pm2_5") or [None])[idx],
        "no2_model": (aq_h.get("nitrogen_dioxide") or [None])[idx],
        "humidity": (wx_h.get("relative_humidity_2m") or [None])[idx],
        "wind_speed": (wx_h.get("wind_speed_10m") or [None])[idx],
        "temperature": (wx_h.get("temperature_2m") or [None])[idx],
        "precipitation": (wx_h.get("precipitation") or [None])[idx],
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
