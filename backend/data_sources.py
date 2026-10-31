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
from typing import Dict, List

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
