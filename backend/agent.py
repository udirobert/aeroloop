"""Self-improvement loop: analyse errors -> propose change -> evaluate on holdout -> keep or reject.

Integrity rules:
- The analysis/tuning step only ever sees the tune split (earlier ~2/3 of matched pairs).
- The holdout split (later ~1/3) is used exclusively to score incumbent vs candidate.
- A candidate is kept only if its holdout MAE is lower than the incumbent's.
- Rejected candidates are still saved as strategies (suffixed "-rejected") — the
  ghost stays in the record.
"""
from __future__ import annotations

import json
import math
import os
import sys
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

from openai import OpenAI

import db
import evaluation
import prediction

LLM_BASE_URL = os.getenv("LLM_BASE_URL", "http://localhost:11434/v1")
LLM_MODEL = os.getenv("LLM_MODEL", "nemotron-mini:latest")
LLM_API_KEY = os.getenv("LLM_API_KEY", "ollama")


def _endpoints() -> List[Tuple[str, str, str]]:
    """OpenAI-compatible endpoints tried in order: primary -> fallback -> local."""
    eps = [(LLM_BASE_URL, LLM_MODEL, LLM_API_KEY)]
    fb_base = os.getenv("LLM_FALLBACK_BASE_URL")
    if fb_base:
        eps.append((
            fb_base,
            os.getenv("LLM_FALLBACK_MODEL", LLM_MODEL),
            os.getenv("LLM_FALLBACK_API_KEY", ""),
        ))
    eps.append((
        os.getenv("LLM_LOCAL_BASE_URL", "http://localhost:11434/v1"),
        os.getenv("LLM_LOCAL_MODEL", "nemotron-mini:latest"),
        os.getenv("LLM_LOCAL_API_KEY", "ollama"),
    ))
    return eps

# sane bounds for anything the LLM proposes
PARAM_BOUNDS = {
    "humidity_coef": (-0.5, 0.5),
    "wind_coef": (-1.0, 1.0),
    "precip_coef": (-5.0, 5.0),
    "bias": (-10.0, 10.0),
}
HOLDOUT_FRACTION = 1 / 3


def _client(base_url: str, api_key: str) -> OpenAI:
    return OpenAI(base_url=base_url, api_key=api_key, timeout=90)


def _clamp(params: Dict[str, Any]) -> Dict[str, float]:
    out = {}
    for k, (lo, hi) in PARAM_BOUNDS.items():
        try:
            v = float(params.get(k, 0.0))
        except (TypeError, ValueError):
            v = 0.0
        out[k] = round(max(lo, min(hi, v)), 4)
    return out


def _parse_llm_json(text: str) -> Dict[str, Any]:
    start = text.find("{")
    end = text.rfind("}") + 1
    if start < 0 or end <= start:
        return {}
    try:
        return json.loads(text[start:end])
    except json.JSONDecodeError:
        return {}


def analyse_errors(
    tune_errors: List[Dict[str, Any]], current_params: Dict[str, Any]
) -> Tuple[Dict[str, str], Optional[Dict[str, float]], str]:
    """Ask the open-weight model to explain the errors AND propose new params.

    Returns (analysis prose, llm_params or None, model_used).
    """
    if not tune_errors:
        return (
            {
                "what_went_wrong": "No errors recorded yet.",
                "pattern_discovered": "n/a",
                "change_made": "none",
                "why_it_should_help": "n/a",
            },
            None,
            "none",
        )
    by_station: Dict[str, List[float]] = {}
    for e in tune_errors:
        by_station.setdefault(e["station_id"], []).append(e["error"])
    worst = max(
        by_station, key=lambda s: abs(sum(by_station[s]) / len(by_station[s]))
    )
    avg_err = sum(e["error"] for e in tune_errors) / len(tune_errors)
    analysis = {
        "what_went_wrong": f"Mean bias {avg_err:+.2f} ug/m3 across {len(tune_errors)} tune-set predictions.",
        "pattern_discovered": f"Largest systematic bias at station '{worst}' (mean error "
        f"{sum(by_station[worst]) / len(by_station[worst]):+.2f}).",
        "change_made": "Adjusted bias/humidity terms (heuristic fallback).",
        "why_it_should_help": "Bias correction counters systematic under/over-prediction.",
    }
    # compact stats + a few samples — small open-weight models handle short
    # prompts with a concrete example far better than raw dumps
    per_station = {s: round(sum(v) / len(v), 2) for s, v in by_station.items()}
    prompt = (
        "You are the reasoning core of a self-improving air-quality agent.\n"
        "Strategy: pred = pm25_model + humidity_coef*(humidity-50) "
        "+ wind_coef*(wind-5) + precip_coef*precipitation + bias\n"
        f"Current params: {json.dumps(current_params)}\n"
        f"Tune-set stats: mean_error={avg_err:+.2f} ug/m3 "
        f"(negative = under-predicting), n={len(tune_errors)}, "
        f"mean_error_by_station={json.dumps(per_station)}\n"
        f"Sample errors (station, predicted, actual, error): "
        f"{json.dumps(tune_errors[:8])}\n\n"
        "Propose new params to reduce systematic error. Be conservative: small "
        "changes from the current values. NOTE: bias POSITIVE raises predictions.\n"
        "Reply ONLY with JSON in this shape (numbers are yours to choose):\n"
        '{"what_went_wrong": "...", "pattern_discovered": "...", '
        '"change_made": "...", "why_it_should_help": "...", '
        '"proposed_params": {"humidity_coef": 0, "wind_coef": 0, '
        '"precip_coef": 0, "bias": 0}}'
    )
    for base_url, model, api_key in _endpoints():
        for attempt in range(2):  # one retry — :free tiers rate-limit transiently
            try:
                resp = _client(base_url, api_key).chat.completions.create(
                    model=model,
                    messages=[{"role": "user", "content": prompt}],
                    temperature=0.2,
                    max_tokens=512,
                )
            except Exception as e:
                if attempt == 0 and "429" in repr(e):
                    import time
                    time.sleep(3)
                    continue  # retry once on rate limit
                print(f"[aeroloop] LLM call failed on {model} @ {base_url}: {e!r}", file=sys.stderr)
                break
            parsed = _parse_llm_json(resp.choices[0].message.content or "")
            prose_ok = False
            for k in ("what_went_wrong", "pattern_discovered", "change_made", "why_it_should_help"):
                if isinstance(parsed.get(k), str):
                    analysis[k] = parsed[k]
                    prose_ok = True
            proposed = parsed.get("proposed_params")
            if isinstance(proposed, dict):
                return analysis, _clamp(proposed), model
            if prose_ok:
                # reasoned fine but didn't propose params — report it and stop
                return analysis, None, f"{model} (analysis only; heuristic params)"
            print(f"[aeroloop] {model} @ {base_url} returned unusable output; trying next endpoint",
                  file=sys.stderr)
            break
    return analysis, None, "unavailable (heuristic fallback)"


def heuristic_params(current: Dict[str, Any], tune_errors: List[Dict[str, Any]]) -> Dict[str, float]:
    """Deterministic fallback when the LLM can't be reached or returns junk."""
    avg_err = sum(e["error"] for e in tune_errors) / len(tune_errors)
    new = dict(current)
    new["bias"] = current.get("bias", 0.0) - avg_err * 0.5
    return _clamp(new)


def _split(matched: List[Dict[str, Any]]) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    """Chronological split: tune on the past, hold out the future."""
    ordered = sorted(matched, key=lambda m: m["timestamp"])
    cut = max(1, int(len(ordered) * (1 - HOLDOUT_FRACTION)))
    if len(ordered) - cut < 2:  # need at least a couple holdout points
        cut = max(0, len(ordered) - 2)
    return ordered[:cut], ordered[cut:]


def _errors_for(strategy_params: Dict[str, Any], pairs: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    errs = []
    for m in pairs:
        pred = prediction.predict("v2-improved", m["inputs"], strategy_params)
        errs.append({"station_id": m["station_id"], "timestamp": m["timestamp"],
                     "predicted": pred, "actual": m["actual"], "error": pred - m["actual"]})
    return errs


def _score(params: Dict[str, Any], pairs: List[Dict[str, Any]]) -> Dict[str, Any]:
    preds = [
        {"station_id": m["station_id"], "timestamp": m["timestamp"],
         "predicted_pm25": prediction.predict("v2-improved", m["inputs"], params)}
        for m in pairs
    ]
    readings = [
        {"station_id": m["station_id"], "timestamp": m["timestamp"], "measured_pm25": m["actual"]}
        for m in pairs
    ]
    return evaluation.evaluate(preds, readings)


def _ver_num(version: str) -> int:
    head = version.split("-")[0].lstrip("v")
    return int(head) if head.isdigit() else -1


TABPFN_FEATURES = ["pm25_model", "no2_model", "humidity", "wind_speed", "temperature", "precipitation"]


def _vec(inputs: Dict[str, Any]) -> List[float]:
    return [float(inputs.get(f) or 0.0) for f in TABPFN_FEATURES]


def _score_tabpfn(tune: List[Dict[str, Any]], holdout: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """Foundation-model challenger: TabPFN regressor trained on the tune split,
    scored on the same holdout as every other candidate. Needs
    TABPFN_ACCESS_TOKEN (free after signing Prior Labs' non-commercial licence)."""
    token = os.getenv("TABPFN_ACCESS_TOKEN")
    if not token or len(tune) < 8 or not holdout:
        return None
    try:
        import tabpfn_client

        tabpfn_client.set_access_token(token)
        reg = tabpfn_client.TabPFNRegressor()
        reg.fit([_vec(m["inputs"]) for m in tune], [m["actual"] for m in tune])
        preds = reg.predict([_vec(m["inputs"]) for m in holdout])
        paired = [
            {"station_id": m["station_id"], "timestamp": m["timestamp"],
             "predicted_pm25": float(p)}
            for m, p in zip(holdout, preds)
        ]
        readings = [
            {"station_id": m["station_id"], "timestamp": m["timestamp"], "measured_pm25": m["actual"]}
            for m in holdout
        ]
        return evaluation.evaluate(paired, readings)
    except Exception as e:
        print(f"[aeroloop] tabpfn challenger failed: {e!r}", file=sys.stderr)
        return {"error": str(e)}


def _next_version(accepted: bool) -> str:
    v = f"v{max((_ver_num(s['version']) for s in db.get_strategies()), default=2) + 1}"
    return v if accepted else f"{v}-rejected"


def _incumbent() -> Tuple[str, Dict[str, Any]]:
    """Highest-numbered accepted *parametric* strategy; falls back to v2 defaults.
    TabPFN-kind rows are recorded for audit but don't serve live predictions yet."""
    strategies = []
    for s in db.get_strategies():
        if s["version"].startswith("v1") or s["version"].endswith("-rejected"):
            continue
        try:
            params = json.loads(s["params"])
        except json.JSONDecodeError:
            continue
        if params.get("kind") == "tabpfn":
            continue
        strategies.append((s, params))
    if not strategies:
        return "v2-improved", dict(prediction.STRATEGY_REGISTRY["v2-improved"]["params"])
    latest, params = max(strategies, key=lambda t: _ver_num(t[0]["version"]))
    return latest["version"], params


def run_self_improvement(matched: List[Dict[str, Any]]) -> Dict[str, Any]:
    """matched: [{station_id, timestamp, inputs, actual}] — only pairs where
    ground truth was retrieved *after* the prediction was stored."""
    from models import Strategy

    tune, holdout = _split(matched)
    incumbent_version, incumbent_params = _incumbent()

    tune_errors = _errors_for(incumbent_params, tune)
    analysis, llm_params, model_used = analyse_errors(tune_errors, incumbent_params)
    candidate_params = llm_params or heuristic_params(incumbent_params, tune_errors)

    before = _score(incumbent_params, holdout)
    after = _score(candidate_params, holdout)
    improved = (not math.isnan(after["mae"])) and after["mae"] < before["mae"]

    db.save_strategy(Strategy(
        version=_next_version(accepted=improved),
        description=analysis["change_made"]
        + f" (proposed by {model_used}; {'kept' if improved else 'REJECTED on holdout'})",
        params=candidate_params,
        created_at=datetime.utcnow(),
        parent_version=incumbent_version,
    ))

    # foundation-model challenger: same tune split, same holdout gate
    challengers = []
    tabpfn = _score_tabpfn(tune, holdout)
    if tabpfn is not None:
        challengers.append({"name": "TabPFN-Regressor", "result": tabpfn})
        tabpfn_mae = tabpfn.get("mae", float("nan")) if isinstance(tabpfn, dict) else float("nan")
        best = min(before["mae"], after["mae"]) if not math.isnan(after["mae"]) else before["mae"]
        if not math.isnan(tabpfn_mae) and tabpfn_mae < best:
            db.save_strategy(Strategy(
                version=f"{_next_version(accepted=True)}-tabpfn",
                description=f"TabPFN regressor (Prior Labs) beat the formula on holdout "
                f"(MAE {tabpfn_mae} vs {best}). Trained on tune split only.",
                params={"kind": "tabpfn", "features": TABPFN_FEATURES},
                created_at=datetime.utcnow(),
                parent_version=incumbent_version,
            ))

    return {
        "what_went_wrong": analysis["what_went_wrong"],
        "pattern_discovered": analysis["pattern_discovered"],
        "change_made": analysis["change_made"],
        "why_it_should_help": analysis["why_it_should_help"],
        "improved": improved,
        "model_used": model_used,
        "params_source": "llm" if llm_params else "heuristic",
        "incumbent_version": incumbent_version,
        "tune_n": len(tune),
        "holdout_n": len(holdout),
        "before": before,
        "after": after,
        "params": candidate_params if improved else incumbent_params,
        "proposed_params": candidate_params,
        "challengers": challengers,
    }
