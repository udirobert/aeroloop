"""Self-improvement loop: analyse errors -> propose change -> evaluate on holdout -> keep or reject.

Integrity rules:
- The analysis/tuning step only ever sees the tune split (earlier ~2/3 of matched pairs).
- The holdout split (later ~1/3) is used exclusively to score incumbent vs candidate.
- A candidate is kept only if its holdout MAE is lower than the incumbent's.
- Rejected candidates are still saved as strategies (suffixed "-rejected") — the
  ghost stays in the record.

Tournament mode (run_tournament): several proposers get byte-identical
(system, user) messages built from tune-split stats only; every proposal is
scored on the same chronological holdout sub-windows; accuracy-eligible
proposals get a Reppo soundness verdict; results persist as a leaderboard.
"""
from __future__ import annotations

import json
import math
import os
import sys
import time
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

from openai import OpenAI

import db
import evaluation
import prediction
import reppo

LLM_BASE_URL = os.getenv("LLM_BASE_URL", "http://localhost:11434/v1")
LLM_MODEL = os.getenv("LLM_MODEL", "nemotron-mini:latest")
LLM_API_KEY = os.getenv("LLM_API_KEY", "ollama")

PROPOSERS_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "proposers.json")


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


# ---------------------------------------------------------------------------
# Shared prompt: ONE (system, user) pair built from tune-split stats only.
# Every LLM proposer gets byte-identical messages — that's what makes the
# tournament fair. Holdout data must never appear here.
# ---------------------------------------------------------------------------

SYSTEM_PROMPT = (
    "You are the reasoning core of a self-improving air-quality agent.\n"
    "Strategy: pred = pm25_model + humidity_coef*(humidity-50) "
    "+ wind_coef*(wind-5) + precip_coef*precipitation + bias\n"
    "Propose new params to reduce systematic error. Be conservative: small "
    "changes from the current values. NOTE: bias POSITIVE raises predictions.\n"
    "Reply ONLY with JSON in this shape (numbers are yours to choose):\n"
    '{"what_went_wrong": "...", "pattern_discovered": "...", '
    '"change_made": "...", "why_it_should_help": "...", '
    '"proposed_params": {"humidity_coef": 0, "wind_coef": 0, '
    '"precip_coef": 0, "bias": 0}}'
)


def _tune_stats(tune_errors: List[Dict[str, Any]]) -> Dict[str, Any]:
    by_station: Dict[str, List[float]] = {}
    for e in tune_errors:
        by_station.setdefault(e["station_id"], []).append(e["error"])
    avg_err = sum(e["error"] for e in tune_errors) / len(tune_errors)
    per_station = {s: round(sum(v) / len(v), 2) for s, v in by_station.items()}
    worst = max(by_station, key=lambda s: abs(per_station[s]))
    return {
        "avg_err": avg_err,
        "n": len(tune_errors),
        "per_station": per_station,
        "worst_station": worst,
        "worst_err": sum(by_station[worst]) / len(by_station[worst]),
    }


def build_messages(
    tune_errors: List[Dict[str, Any]], current_params: Dict[str, Any]
) -> Tuple[str, str]:
    """Return (system, user) built ONLY from tune-split stats and current params."""
    stats = _tune_stats(tune_errors)
    user = (
        f"Current params: {json.dumps(current_params)}\n"
        f"Tune-set stats: mean_error={stats['avg_err']:+.2f} ug/m3 "
        f"(negative = under-predicting), n={stats['n']}, "
        f"mean_error_by_station={json.dumps(stats['per_station'])}\n"
        f"Sample errors (station, predicted, actual, error): "
        f"{json.dumps(tune_errors[:8])}\n\n"
        "Propose new params."
    )
    return SYSTEM_PROMPT, user


def _fallback_analysis(tune_errors: List[Dict[str, Any]]) -> Dict[str, str]:
    stats = _tune_stats(tune_errors)
    return {
        "what_went_wrong": f"Mean bias {stats['avg_err']:+.2f} ug/m3 across "
        f"{stats['n']} tune-set predictions.",
        "pattern_discovered": f"Largest systematic bias at station "
        f"'{stats['worst_station']}' (mean error {stats['worst_err']:+.2f}).",
        "change_made": "Adjusted bias/humidity terms (heuristic fallback).",
        "why_it_should_help": "Bias correction counters systematic under/over-prediction.",
    }


def _cost_usd(
    prompt_tokens: Optional[int], completion_tokens: Optional[int],
    price_in: Optional[float], price_out: Optional[float],
) -> Optional[float]:
    if prompt_tokens is None or completion_tokens is None:
        return None
    if price_in is None or price_out is None:
        return None
    return round((prompt_tokens * price_in + completion_tokens * price_out) / 1e6, 6)


# SERV's BRAID scaffold reshapes the JSON contract per model tier rather than
# echoing the requested keys: serv-ultra returns reasoning{...}+proposed_params,
# serv-nano returns error_summary{...}+change_plan{...}+updated_params. Both are
# valid JSON, so the audit normalises them onto one canonical record.
_PARAM_KEYS = ("proposed_params", "updated_params", "new_params", "proposed_parameters")
_CURRENT_HINTS = ("current", "old", "existing", "baseline", "before", "input")
_PROSE_ALIASES = {
    "what_went_wrong": ("what_went_wrong", "error_analysis", "error_summary",
                        "evidence", "error_pattern"),
    "pattern_discovered": ("pattern_discovered", "discovered_pattern", "error_pattern"),
    "change_made": ("change_made", "proposed_change", "directional_adjustment",
                    "changes", "change_magnitude"),
    "why_it_should_help": ("why_it_should_help", "expected_benefit", "change_rationale",
                           "rationale_for_not_more_aggressive_changes", "explanation"),
}


def _params_by_content(parsed: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Identify the params object by the parameter space it holds, not its name.

    SERV renames it between calls on an identical prompt (proposed_params,
    updated_params, new_params, proposed_parameters). Some schemas also echo the
    current params, which must never be mistaken for a proposal.
    """
    best = None
    best_hits = 0
    for key, val in parsed.items():
        if not isinstance(val, dict) or not val:
            continue
        if any(h in key.lower() for h in _CURRENT_HINTS):
            continue
        if not all(isinstance(v, (int, float)) for v in val.values()):
            continue
        hits = len(set(val) & set(PARAM_BOUNDS))
        if hits > best_hits:
            best, best_hits = val, hits
    return best


def _canonical_analysis(
    parsed: Dict[str, Any],
) -> Tuple[Dict[str, str], Optional[Dict[str, Any]]]:
    """Map a proposer's JSON onto (canonical prose fields, params dict)."""
    flat: Dict[str, Any] = {}
    for v in parsed.values():
        if isinstance(v, dict):
            flat.update(v)
    flat.update(parsed)  # top-level keys win over nested ones
    analysis: Dict[str, str] = {}
    for canon, aliases in _PROSE_ALIASES.items():
        for alias in aliases:
            if isinstance(flat.get(alias), str):
                analysis[canon] = flat[alias]
                break
    params = next((flat[k] for k in _PARAM_KEYS if isinstance(flat.get(k), dict)), None)
    if params is None:
        params = _params_by_content(parsed)
    return analysis, params


def call_llm(
    base_url: str, model: str, api_key: str, messages: List[Dict[str, str]],
    price_in: Optional[float] = None, price_out: Optional[float] = None,
    token_param: str = "max_tokens",
) -> Dict[str, Any]:
    """One OpenAI-compatible chat call (one retry on 429).

    Returns {status, analysis, params, latency_ms, prompt_tokens,
    completion_tokens, cost_usd, error, response_id, finish_reason,
    cached_tokens, reasoning_tokens, response_schema}.
    """
    out: Dict[str, Any] = {
        "status": "error", "analysis": {}, "params": None,
        "latency_ms": None, "prompt_tokens": None, "completion_tokens": None,
        "cost_usd": None, "error": None, "response_id": None,
        "finish_reason": None, "cached_tokens": None, "reasoning_tokens": None,
        "response_schema": None,
    }
    resp = None
    for attempt in range(2):  # one retry — :free tiers rate-limit transiently
        try:
            t0 = time.monotonic()
            resp = _client(base_url, api_key).chat.completions.create(
                model=model,
                messages=messages,
                temperature=0.2,
                **{token_param: 800},
            )
            out["latency_ms"] = round((time.monotonic() - t0) * 1000)
            break
        except Exception as e:
            if attempt == 0 and "429" in repr(e):
                time.sleep(3)
                continue
            out["error"] = repr(e)
            return out
    if resp is None:
        out["error"] = "no response"
        return out

    out["response_id"] = getattr(resp, "id", None)
    choice = resp.choices[0]
    out["finish_reason"] = getattr(choice, "finish_reason", None)
    usage = getattr(resp, "usage", None)
    if usage is not None:
        out["prompt_tokens"] = getattr(usage, "prompt_tokens", None)
        out["completion_tokens"] = getattr(usage, "completion_tokens", None)
        out["cost_usd"] = _cost_usd(
            out["prompt_tokens"], out["completion_tokens"], price_in, price_out
        )
        # SERV serves its BRAID reasoning graph from a per-org cache keyed on the
        # system prompt; cached_tokens is the observable evidence of that cache.
        pd = getattr(usage, "prompt_tokens_details", None)
        if pd is not None:
            out["cached_tokens"] = getattr(pd, "cached_tokens", None)
        cd = getattr(usage, "completion_tokens_details", None)
        if cd is not None:
            out["reasoning_tokens"] = getattr(cd, "reasoning_tokens", None)

    parsed = _parse_llm_json(choice.message.content or "")
    out["response_schema"] = sorted(parsed.keys())
    analysis, proposed = _canonical_analysis(parsed)
    out["analysis"] = analysis
    if isinstance(proposed, dict):
        out["params"] = _clamp(proposed)
        out["status"] = "ok"
    elif out["finish_reason"] == "content_filter":
        # SERV refuses benign prompts intermittently. We do not disable its
        # filter; the refusal is a reliability finding and stays in the record.
        out["status"] = "error"
        out["error"] = "SERV content filter refused the request"
    elif analysis:
        out["status"] = "no_params"
        out["error"] = "analysis only; no proposed_params"
    else:
        out["status"] = "error"
        out["error"] = "unusable output"
    return out


def load_proposers() -> List[Dict[str, Any]]:
    with open(PROPOSERS_PATH) as f:
        return json.load(f)["proposers"]


def resolve_proposer(cfg: Dict[str, Any]) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
    """Resolve env-referenced fields. Returns (resolved, missing_reason)."""
    if not cfg.get("enabled", True):
        return None, "disabled in proposers.json"
    base_url = (
        cfg.get("base_url")
        or os.getenv(cfg.get("base_url_env", ""), "")
        or cfg.get("base_url_default")
    )
    if not base_url:
        return None, f"missing {cfg.get('base_url_env', 'base_url')}"
    model = (
        cfg.get("model")
        or os.getenv(cfg.get("model_env", ""), "")
        or cfg.get("model_default")
    )
    if not model:
        return None, f"missing {cfg.get('model_env', 'model')}"
    key_env = cfg.get("api_key_env")
    api_key = os.getenv(key_env, "") if key_env else ""
    api_key = api_key or cfg.get("api_key_default", "")
    if not api_key:
        return None, f"missing {key_env}"
    return {
        "base_url": base_url, "model": model, "api_key": api_key,
        "price_in_per_m": cfg.get("price_in_per_m"),
        "price_out_per_m": cfg.get("price_out_per_m"),
        "token_param": cfg.get("token_param", "max_tokens"),
    }, None


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
    analysis = _fallback_analysis(tune_errors)
    system, user = build_messages(tune_errors, current_params)
    messages = [{"role": "system", "content": system}, {"role": "user", "content": user}]
    for base_url, model, api_key in _endpoints():
        r = call_llm(base_url, model, api_key, messages)
        if r["status"] == "ok":
            for k, v in r["analysis"].items():
                analysis[k] = v
            return analysis, r["params"], model
        if r["status"] == "no_params":
            for k, v in r["analysis"].items():
                analysis[k] = v
            return analysis, None, f"{model} (analysis only; heuristic params)"
        print(f"[aeroloop] LLM call failed on {model} @ {base_url}: {r['error']}",
              file=sys.stderr)
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


def holdout_windows(holdout: List[Dict[str, Any]], k: Optional[int] = None) -> List[List[Dict[str, Any]]]:
    """Split the holdout chronologically into K contiguous windows.

    K (env TOURNAMENT_WINDOWS, default 3) is reduced so each window has
    >=2 pairs; minimum 1 window.
    """
    if k is None:
        k = int(os.getenv("TOURNAMENT_WINDOWS", "3"))
    n = len(holdout)
    if n == 0:
        return []
    while k > 1 and n // k < 2:
        k -= 1
    k = max(1, k)
    return [holdout[i * n // k:(i + 1) * n // k] for i in range(k)]


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


def _tabpfn_predict(
    tune: List[Dict[str, Any]], pairs: List[Dict[str, Any]]
) -> Optional[Any]:
    """Fit TabPFN on the tune split and predict `pairs`.

    Returns a list of floats aligned to `pairs`, {"error": ...} on failure,
    or None when not configured (needs TABPFN_ACCESS_TOKEN, free after signing
    Prior Labs' non-commercial licence).
    """
    token = os.getenv("TABPFN_ACCESS_TOKEN")
    if not token or len(tune) < 8 or not pairs:
        return None
    try:
        import numpy as np
        import tabpfn_client

        tabpfn_client.set_access_token(token)
        reg = tabpfn_client.TabPFNRegressor()
        reg.fit(
            np.array([_vec(m["inputs"]) for m in tune]),
            np.array([m["actual"] for m in tune]),
        )
        preds = reg.predict(np.array([_vec(m["inputs"]) for m in pairs]))
        return [float(p) for p in preds]
    except Exception as e:
        print(f"[aeroloop] tabpfn challenger failed: {e!r}", file=sys.stderr)
        return {"error": str(e)}


def _eval_preds(preds: List[float], pairs: List[Dict[str, Any]]) -> Dict[str, Any]:
    paired = [
        {"station_id": m["station_id"], "timestamp": m["timestamp"],
         "predicted_pm25": p}
        for m, p in zip(pairs, preds)
    ]
    readings = [
        {"station_id": m["station_id"], "timestamp": m["timestamp"], "measured_pm25": m["actual"]}
        for m in pairs
    ]
    return evaluation.evaluate(paired, readings)


def _score_tabpfn(tune: List[Dict[str, Any]], holdout: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """Foundation-model challenger: TabPFN regressor trained on the tune split,
    scored on the same holdout as every other candidate."""
    preds = _tabpfn_predict(tune, holdout)
    if preds is None:
        return None
    if isinstance(preds, dict):
        return preds
    return _eval_preds(preds, holdout)


def _next_version(accepted: bool) -> str:
    v = f"v{max((_ver_num(s['version']) for s in db.get_strategies()), default=2) + 1}"
    return v if accepted else f"{v}-rejected"


def _incumbent() -> Tuple[str, Dict[str, Any]]:
    """Highest-numbered accepted *parametric* strategy; falls back to v2 defaults.
    TabPFN-kind rows are recorded for audit but don't serve live predictions yet."""
    strategies = []
    for s in db.get_strategies():
        if _ver_num(s["version"]) < 2 or s["version"].endswith("-rejected"):
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


# ---------------------------------------------------------------------------
# Correction tournament
# ---------------------------------------------------------------------------

def _mae(scored: Optional[Dict[str, Any]]) -> float:
    if not scored:
        return float("nan")
    m = scored.get("mae", float("nan"))
    return m if isinstance(m, (int, float)) else float("nan")


def _reppo_input(
    tune_stats: Dict[str, Any], tune_errors: List[Dict[str, Any]],
    current_params: Dict[str, Any], proposal: Dict[str, Any],
) -> str:
    """Text for the soundness eval. Deliberately contains NO holdout metrics —
    soundness is judged independently of the outcome."""
    return (
        "TASK: propose correction params for a PM2.5 correction strategy given "
        "tune-split error statistics. The proposal is judged for soundness, "
        "not outcome.\n"
        "STRATEGY FORMULA: pred = pm25_model + humidity_coef*(humidity-50) "
        "+ wind_coef*(wind-5) + precip_coef*precipitation + bias\n"
        f"CURRENT PARAMS: {json.dumps(current_params)}\n"
        f"TUNE-SPLIT STATS SHOWN TO THE PROPOSER: mean_error={tune_stats['avg_err']:+.2f} "
        f"ug/m3, n={tune_stats['n']}, "
        f"mean_error_by_station={json.dumps(tune_stats['per_station'])}; "
        f"sample errors (first 8): {json.dumps(tune_errors[:8])}\n"
        f"PROPOSER: {proposal['proposer']} (model {proposal.get('model')})\n"
        f"PROPOSAL ANALYSIS: {json.dumps(proposal.get('analysis', {}))}\n"
        f"PROPOSED PARAMS: {json.dumps(proposal.get('params'))}\n"
        "JUDGE: are the proposed signs/magnitudes physically plausible; is the "
        "change conservative relative to the current params; does the proposal "
        "rely only on tune-split data (no future/holdout information); does "
        "the stated reasoning match the numbers."
    )


def run_tournament(matched: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Fair correction tournament: identical prompt, shared holdout windows,
    Reppo soundness gate on accuracy-eligible proposals."""
    from models import Strategy

    tune, holdout = _split(matched)
    windows = holdout_windows(holdout)
    n_windows = len(windows)
    incumbent_version, incumbent_params = _incumbent()
    incumbent_scores = {
        "whole": _score(incumbent_params, holdout),
        "windows": [_score(incumbent_params, w) for w in windows],
    }
    inc_mae = _mae(incumbent_scores["whole"])

    tune_errors = _errors_for(incumbent_params, tune)
    tune_stats = _tune_stats(tune_errors)
    system, user = build_messages(tune_errors, incumbent_params)
    messages = [{"role": "system", "content": system}, {"role": "user", "content": user}]

    proposals: List[Dict[str, Any]] = []

    def _score_proposal(rec: Dict[str, Any]) -> None:
        scored = {
            "whole": _score(rec["params"], holdout),
            "windows": [_score(rec["params"], w) for w in windows],
        }
        rec["holdout"] = scored
        rec["windows_won"] = sum(
            1 for w_s, i_s in zip(scored["windows"], incumbent_scores["windows"])
            if _mae(w_s) < _mae(i_s)
        )
        rec["eligible"] = bool(
            n_windows
            and not math.isnan(_mae(scored["whole"]))
            and _mae(scored["whole"]) < inc_mae
            and rec["windows_won"] > n_windows / 2
        )

    # --- LLM proposers: byte-identical messages for everyone ---
    for cfg in load_proposers():
        rec: Dict[str, Any] = {
            "proposer": cfg["name"], "label": cfg.get("label", cfg["name"]),
            "model": None, "uses_serv": bool(cfg.get("uses_serv")),
            "status": None, "error": None, "analysis": None, "params": None,
            "holdout": None, "windows_won": None, "eligible": False,
            "latency_ms": None, "prompt_tokens": None, "completion_tokens": None,
            "cost_usd": None, "gate_status": None, "reppo": None,
            "note": cfg.get("note"),
        }
        resolved, missing = resolve_proposer(cfg)
        if resolved is None:
            rec["status"] = "skipped"
            rec["error"] = missing
            proposals.append(rec)
            continue
        rec["model"] = resolved["model"]
        r = call_llm(
            resolved["base_url"], resolved["model"], resolved["api_key"], messages,
            price_in=resolved["price_in_per_m"], price_out=resolved["price_out_per_m"],
            token_param=resolved["token_param"],
        )
        rec.update({k: r[k] for k in ("status", "error", "analysis", "params",
                                      "latency_ms", "prompt_tokens",
                                      "completion_tokens", "cost_usd",
                                      "response_id", "finish_reason",
                                      "cached_tokens", "reasoning_tokens",
                                      "response_schema")})
        if rec["status"] == "no_params" and rec["analysis"]:
            rec["error"] = rec["error"] or "no proposed_params"
        if rec["params"] is not None:
            _score_proposal(rec)
        proposals.append(rec)

    # --- heuristic entrant (deterministic, always runs) ---
    h_params = heuristic_params(incumbent_params, tune_errors)
    h_rec: Dict[str, Any] = {
        "proposer": "heuristic", "label": "Deterministic heuristic",
        "model": "heuristic", "uses_serv": False,
        "status": "ok", "error": None,
        "analysis": _fallback_analysis(tune_errors), "params": h_params,
        "holdout": None, "windows_won": None, "eligible": False,
        "latency_ms": None, "prompt_tokens": None, "completion_tokens": None,
        "cost_usd": None, "gate_status": None, "reppo": None, "note": None,
    }
    _score_proposal(h_rec)
    proposals.append(h_rec)

    # --- TabPFN challenger: scored on the same sub-windows, never live-eligible ---
    tabpfn_preds = _tabpfn_predict(tune, holdout)
    tabpfn: Optional[Dict[str, Any]] = None
    if tabpfn_preds is not None:
        t_rec: Dict[str, Any] = {
            "proposer": "tabpfn", "label": "TabPFN-Regressor (Prior Labs)",
            "model": "tabpfn", "uses_serv": False,
            "status": "ok" if isinstance(tabpfn_preds, list) else "error",
            "error": None if isinstance(tabpfn_preds, list) else tabpfn_preds.get("error"),
            "analysis": None, "params": None,
            "holdout": None, "windows_won": None, "eligible": False,
            "latency_ms": None, "prompt_tokens": None, "completion_tokens": None,
            "cost_usd": None, "gate_status": "ineligible", "reppo": None,
            "note": "predictor, not a param proposer — ineligible to become the live strategy",
        }
        if isinstance(tabpfn_preds, list):
            tabpfn = _eval_preds(tabpfn_preds, holdout)
            window_scores = []
            idx = 0
            for w in windows:
                window_scores.append(_eval_preds(tabpfn_preds[idx:idx + len(w)], w))
                idx += len(w)
            t_rec["holdout"] = {"whole": tabpfn, "windows": window_scores}
            t_rec["windows_won"] = sum(
                1 for w_s, i_s in zip(window_scores, incumbent_scores["windows"])
                if _mae(w_s) < _mae(i_s)
            )
        else:
            tabpfn = tabpfn_preds
        proposals.append(t_rec)

    # --- Reppo soundness gate on accuracy-eligible proposals, best MAE first ---
    eligible = sorted(
        (p for p in proposals if p["eligible"]),
        key=lambda p: _mae(p["holdout"]["whole"]),
    )
    for p in eligible:
        gate = reppo.run_gate(_reppo_input(tune_stats, tune_errors, incumbent_params, p))
        p["gate_status"] = gate["status"]
        p["reppo"] = gate["reppo"]

    # --- winner rule ---
    scored_ok = [p for p in proposals if p["params"] is not None and p["holdout"]]
    accepted = next((p for p in eligible if p["gate_status"] in ("accept", "not_configured")), None)
    strategy_row: Optional[Dict[str, Any]] = None
    if accepted is not None:
        gate_desc = ("soundness gate accepted" if accepted["gate_status"] == "accept"
                     else "soundness gate not configured (no REPPO_API_KEY)")
        strategy_row = {
            "version": _next_version(accepted=True),
            "description": (f"{(accepted.get('analysis') or {}).get('change_made', 'param update')} "
                            f"(proposed by {accepted['proposer']}/{accepted.get('model')}; kept; "
                            f"{gate_desc})"),
            "params": accepted["params"],
            "outcome": "winner",
            "winner": accepted["proposer"],
        }
    elif eligible:
        best = eligible[0]
        gate_reason = (best.get("reppo") or {}).get("reason") or best["gate_status"]
        strategy_row = {
            "version": _next_version(accepted=False),
            "description": (f"{(best.get('analysis') or {}).get('change_made', 'param update')} "
                            f"(proposed by {best['proposer']}/{best.get('model')}; REJECTED — "
                            f"accuracy-eligible but soundness gate "
                            f"{best['gate_status']}: {gate_reason})"),
            "params": best["params"],
            "outcome": "gate_rejected",
            "winner": None,
        }
    else:
        best = min(scored_ok, key=lambda p: _mae(p["holdout"]["whole"]), default=None)
        if best is not None:
            strategy_row = {
                "version": _next_version(accepted=False),
                "description": (f"{(best.get('analysis') or {}).get('change_made', 'param update')} "
                                f"(proposed by {best['proposer']}/{best.get('model')}; REJECTED — "
                                "no proposal beat incumbent on holdout)"),
                "params": best["params"],
                "outcome": "no_eligible",
                "winner": None,
            }

    strategy_version = None
    if strategy_row is not None:
        strategy_version = strategy_row["version"]
        db.save_strategy(Strategy(
            version=strategy_version,
            description=strategy_row["description"],
            params=strategy_row["params"],
            created_at=datetime.utcnow(),
            parent_version=incumbent_version,
        ))

    # TabPFN audit row: recorded if it beat incumbent AND the best parametric candidate
    if tabpfn is not None and "error" not in tabpfn:
        tabpfn_mae = _mae(tabpfn)
        candidates = [inc_mae] + [_mae(p["holdout"]["whole"]) for p in scored_ok]
        best = min(c for c in candidates if not math.isnan(c))
        if not math.isnan(tabpfn_mae) and tabpfn_mae < best:
            db.save_strategy(Strategy(
                version=f"{_next_version(accepted=True)}-tabpfn",
                description=f"TabPFN regressor (Prior Labs) beat the formula on holdout "
                f"(MAE {tabpfn_mae} vs {best}). Trained on tune split only.",
                params={"kind": "tabpfn", "features": TABPFN_FEATURES},
                created_at=datetime.utcnow(),
                parent_version=incumbent_version,
            ))

    leaderboard = sorted(
        proposals,
        key=lambda p: (math.isnan(_mae((p.get("holdout") or {}).get("whole"))),
                       _mae((p.get("holdout") or {}).get("whole"))),
    )
    run = {
        "created_at": datetime.utcnow().isoformat(),
        "incumbent_version": incumbent_version,
        "tune_n": len(tune),
        "holdout_n": len(holdout),
        "windows": n_windows,
        "winner": strategy_row["winner"] if strategy_row else None,
        "strategy_version": strategy_version,
        "outcome": strategy_row["outcome"] if strategy_row else "no_proposals",
        "incumbent_scores": incumbent_scores,
        "proposals": leaderboard,
    }
    run_id = db.save_tournament_run(run)
    run["id"] = run_id
    return run
