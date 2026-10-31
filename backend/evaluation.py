"""Evaluation: MAE, RMSE, bias on a fixed held-out benchmark."""
from __future__ import annotations

import math
from typing import Any, Dict, List


def evaluate(predictions: List[Dict[str, Any]], readings: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Match predictions to ground readings by (station, timestamp) and score."""
    reading_map = {(r["station_id"], r["timestamp"]): r["measured_pm25"] for r in readings}
    matched = []
    for p in predictions:
        key = (p["station_id"], p["timestamp"])
        if key in reading_map:
            actual = reading_map[key]
            err = p["predicted_pm25"] - actual
            matched.append(
                {
                    "station_id": p["station_id"],
                    "timestamp": p["timestamp"],
                    "predicted": p["predicted_pm25"],
                    "actual": actual,
                    "error": err,
                    "abs_error": abs(err),
                    "squared_error": err * err,
                }
            )
    if not matched:
        return {"n": 0, "mae": float("nan"), "rmse": float("nan"), "bias": float("nan"),
                "by_station": {}, "by_condition": {}}

    n = len(matched)
    mae = sum(m["abs_error"] for m in matched) / n
    rmse = math.sqrt(sum(m["squared_error"] for m in matched) / n)
    bias = sum(m["error"] for m in matched) / n

    by_station: Dict[str, Dict[str, float]] = {}
    for m in matched:
        s = by_station.setdefault(m["station_id"], {"n": 0, "ae": 0.0, "se": 0.0, "e": 0.0})
        s["n"] += 1
        s["ae"] += m["abs_error"]
        s["se"] += m["squared_error"]
        s["e"] += m["error"]
    for s in by_station.values():
        s["mae"] = s["ae"] / s["n"]
        s["rmse"] = (s["se"] / s["n"]) ** 0.5
        s["bias"] = s["e"] / s["n"]

    return {"n": n, "mae": round(mae, 3), "rmse": round(rmse, 3), "bias": round(bias, 3),
            "by_station": by_station, "by_condition": {}}
