"""Prediction strategies: baseline (v1) and improved (v2).

Each strategy is a versioned, inspectable function. The agent can rewrite
strategy params by editing the strategy JSON on disk (see agent.py).
"""
from __future__ import annotations

from typing import Any, Dict


def baseline_v1(features: Dict[str, Any]) -> float:
    """v1: trust the CAMS model PM2.5, lightly corrected for humidity."""
    pm = features.get("pm25_model")
    if pm is None:
        return 0.0
    humidity = features.get("humidity") or 50.0
    # simple correction: high humidity inflates model PM2.5
    correction = 1.0 - (humidity - 50.0) * 0.002
    return round(float(pm) * correction, 2)


def improved_v2(features: Dict[str, Any], params: Dict[str, Any]) -> float:
    """v2: model PM2.5 + weather + (optional) road-density correction.

    params can be rewritten by the agent, e.g.:
      {"humidity_coef": -0.05, "wind_coef": -0.3, "road_coef": 1.2, "bias": 2.0}
    """
    pm = features.get("pm25_model")
    if pm is None:
        return 0.0
    humidity = features.get("humidity") or 50.0
    wind = features.get("wind_speed") or 5.0
    precip = features.get("precipitation") or 0.0

    humidity_coef = params.get("humidity_coef", -0.05)
    wind_coef = params.get("wind_coef", -0.3)
    precip_coef = params.get("precip_coef", -0.5)
    bias = params.get("bias", 2.0)

    val = float(pm)
    val += humidity_coef * (humidity - 50.0)
    val += wind_coef * (wind - 5.0)
    val += precip_coef * precip
    val += bias
    return round(max(0.0, val), 2)


STRATEGY_REGISTRY = {
    "v1-baseline": {"fn": baseline_v1, "params": {}},
    "v2-improved": {
        "fn": improved_v2,
        "params": {"humidity_coef": -0.05, "wind_coef": -0.3, "precip_coef": -0.5, "bias": 2.0},
    },
}


def predict(
    strategy_version: str, features: Dict[str, Any], params: Dict[str, Any] | None = None
) -> float:
    entry = STRATEGY_REGISTRY[strategy_version]
    fn = entry["fn"]
    p = params if params is not None else entry["params"]
    if strategy_version.startswith("v1"):
        return fn(features)
    return fn(features, p)
