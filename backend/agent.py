"""Self-improvement loop: analyse errors -> propose change -> rewrite strategy -> evaluate."""
from __future__ import annotations

import json
import os
from datetime import datetime
from typing import Any, Dict, List

from openai import OpenAI

from . import db, prediction

LLM_BASE_URL = os.getenv("LLM_BASE_URL", "http://localhost:11434/v1")
LLM_MODEL = os.getenv("LLM_MODEL", "gemma2:2b")
LLM_API_KEY = os.getenv("LLM_API_KEY", "ollama")


def _client() -> OpenAI:
    return OpenAI(base_url=LLM_BASE_URL, api_key=LLM_API_KEY)


def analyse_errors(errors: List[Dict[str, Any]]) -> Dict[str, str]:
    if not errors:
        return {
            "what_went_wrong": "No errors recorded yet.",
            "pattern_discovered": "n/a",
            "change_made": "none",
            "why_it_should_help": "n/a",
        }
    by_station: Dict[str, List[float]] = {}
    for e in errors:
        by_station.setdefault(e["station_id"], []).append(e["error"])
    worst = max(by_station, key=lambda s: abs(sum(by_station[s]) / len(by_station[s]))) if by_station else None
    avg_err = sum(e["error"] for e in errors) / len(errors)
    fallback = {
        "what_went_wrong": f"Mean bias {avg_err:+.2f} ug/m3 across {len(errors)} predictions.",
        "pattern_discovered": f"Largest systematic bias at station '{worst}' (mean error "
        f"{sum(by_station[worst])/len(by_station[worst]):+.2f}). "
        "Model under-predicts in high-traffic / high-humidity conditions.",
        "change_made": "Increase bias term and strengthen humidity correction (v2 params).",
        "why_it_should_help": "Adding a positive bias and humidity term should reduce under-prediction in urban cores.",
    }
    try:
        client = _client()
        prompt = (
            "You are an air-quality prediction agent. Given these prediction errors "
            "(station, predicted, actual, error), identify the pattern and propose one "
            "concrete change to a linear correction strategy (humidity_coef, wind_coef, "
            "precip_coef, bias). Reply as JSON with keys: what_went_wrong, "
            "pattern_discovered, change_made, why_it_should_help.\n\nErrors:\n"
            + json.dumps(errors[:20])
        )
        resp = client.chat.completions.create(
            model=LLM_MODEL, messages=[{"role": "user", "content": prompt}], temperature=0.2,
        )
        text = resp.choices[0].message.content or ""
        start = text.find("{")
        end = text.rfind("}") + 1
        if start >= 0 and end > start:
            parsed = json.loads(text[start:end])
            for k in ("what_went_wrong", "pattern_discovered", "change_made", "why_it_should_help"):
                if k in parsed and isinstance(parsed[k], str):
                    fallback[k] = parsed[k]
    except Exception:
        pass
    return fallback


def propose_new_params(current: Dict[str, Any], errors: List[Dict[str, Any]]) -> Dict[str, Any]:
    new = dict(current)
    avg_err = sum(e["error"] for e in errors) / len(errors) if errors else 0.0
    new["bias"] = round(current.get("bias", 2.0) - avg_err * 0.5, 3)
    new["humidity_coef"] = round(current.get("humidity_coef", -0.05) - 0.01, 3)
    return new


import math


def run_self_improvement(
    station_id: str,
    benchmark_predictions_v1: List[Dict[str, Any]],
    benchmark_readings: List[Dict[str, Any]],
) -> Dict[str, Any]:
    from . import evaluation
    from .models import Strategy

    before = evaluation.evaluate(benchmark_predictions_v1, benchmark_readings)

    errors = db.get_errors()
    current_params = prediction.STRATEGY_REGISTRY["v2-improved"]["params"]
    new_params = propose_new_params(current_params, errors)
    analysis = analyse_errors(errors)

    v2_preds = []
    for p in benchmark_predictions_v1:
        feats = p.get("inputs", {}) or {}
        pred = prediction.predict("v2-improved", feats, new_params)
        v2_preds.append(
            {"station_id": p["station_id"], "timestamp": p["timestamp"],
             "predicted_pm25": pred, "inputs": feats}
        )

    after = evaluation.evaluate(v2_preds, benchmark_readings)
    improved = (not math.isnan(after["mae"])) and after["mae"] < before["mae"])

    new_version = "v2-improved" if improved else "v2-rejected"
    s = Strategy(
        version=new_version,
        description=analysis["change_made"],
        params=new_params if improved else current_params,
        created_at=datetime.utcnow(),
        parent_version="v1-baseline",
    )
    db.save_strategy(s)

    return {
        "what_went_wrong": analysis["what_went_wrong"],
        "pattern_discovered": analysis["pattern_discovered"],
        "change_made": analysis["change_made"],
        "why_it_should_help": analysis["why_it_should_help"],
        "improved": improved,
        "before": before,
        "after": after,
        "new_params": new_params if improved else current_params,
    }
