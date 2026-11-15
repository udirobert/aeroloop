"""Subject-agnostic trust scoring against reference monitors.

Compares an hourly subject series (a low-cost sensor, a model field, a
strategy's predictions) with a reference series. Aggregation is to UTC days —
the US EPA 2021 PM2.5 sensor performance targets are defined on 24-hour
averages — keeping days with >= 18/24 paired hours (75%).

EPA checks (daily means, regression of subject (y) on reference (x)):
    data completeness >= 75%, R^2 >= 0.70, slope within 1.0 ± 0.35,
    -5 <= intercept <= 5 µg/m³, RMSE <= 7 µg/m³ OR NRMSE <= 30% (either ok).
This is an indicative comparison, not certification.

Drift is an AeroLoop heuristic (not EPA): chronological halves of the daily
series; drift_flag when |bias(second) - bias(first)| > max(2.0, 0.25 * mean
reference).
"""
from __future__ import annotations

import os
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

TRUST_MIN_DAYS = int(os.getenv("TRUST_MIN_DAYS", "7"))
MIN_DAY_HOURS = 18  # 75% of 24

STANDARD = ("US EPA 2021 PM2.5 sensor performance targets (24-h averages)"
            " — indicative comparison, not certification")

Triple = Tuple[str, float, float]  # (iso_timestamp, subject, reference)


def daily_means(triples: List[Triple]) -> List[Tuple[str, float, float, int]]:
    """UTC-day means for days with >= MIN_DAY_HOURS paired hours.

    Returns [(day, subject_mean, reference_mean, n_hours)] chronological.
    """
    days: Dict[str, List[Tuple[float, float]]] = {}
    for ts, sv, rv in triples:
        if sv is None or rv is None:
            continue
        day = ts[:10]
        days.setdefault(day, []).append((sv, rv))
    out = []
    for day in sorted(days):
        pairs = days[day]
        if len(pairs) < MIN_DAY_HOURS:
            continue
        out.append((day,
                    sum(p[0] for p in pairs) / len(pairs),
                    sum(p[1] for p in pairs) / len(pairs),
                    len(pairs)))
    return out


def _ols(x: List[float], y: List[float]) -> Tuple[float, float]:
    mx, my = sum(x) / len(x), sum(y) / len(y)
    sxx = sum((v - mx) ** 2 for v in x)
    if sxx == 0:
        return 0.0, my
    slope = sum((a - mx) * (b - my) for a, b in zip(x, y)) / sxx
    return slope, my - slope * mx


def score_triples(triples: List[Triple],
                  min_days: Optional[int] = None) -> Dict[str, Any]:
    """Full trust metrics for hourly (timestamp, subject, reference) triples."""
    min_days = TRUST_MIN_DAYS if min_days is None else min_days
    daily = daily_means(triples)
    n_days = len(daily)
    # completeness: valid days / days spanned by the daily record
    if daily:
        d0 = datetime.fromisoformat(daily[0][0])
        d1 = datetime.fromisoformat(daily[-1][0])
        total_days = (d1 - d0).days + 1
        completeness = n_days / total_days if total_days else 0.0
    else:
        total_days = 0
        completeness = 0.0

    # hourly metrics (informational)
    hp = [(s, r) for _, s, r in triples if s is not None and r is not None]
    hourly = {
        "n": len(hp),
        "mae": (sum(abs(s - r) for s, r in hp) / len(hp)) if hp else None,
        "rmse": (sum((s - r) ** 2 for s, r in hp) / len(hp)) ** 0.5 if hp else None,
        "bias": (sum(s - r for s, r in hp) / len(hp)) if hp else None,
    }

    if n_days >= 2:
        xs = [d[2] for d in daily]
        ys = [d[1] for d in daily]
        slope, intercept = _ols(xs, ys)
        mx = sum(xs) / len(xs)
        my = sum(ys) / len(ys)
        ss_tot = sum((v - my) ** 2 for v in ys)
        ss_res = sum((a - b) ** 2 for a, b in zip(ys, xs))
        # R^2 = squared Pearson correlation (per EPA performance targets)
        sxx = sum((v - mx) ** 2 for v in xs)
        syy = ss_tot
        sxy = sum((a - mx) * (b - my) for a, b in zip(xs, ys))
        r2 = (sxy * sxy) / (sxx * syy) if sxx and syy else 0.0
        rmse = (ss_res / n_days) ** 0.5
        mae = sum(abs(a - b) for a, b in zip(ys, xs)) / n_days
        bias = sum(a - b for a, b in zip(ys, xs)) / n_days
        nrmse = rmse / mx if mx else None

        # drift heuristic: chronological halves
        h = n_days // 2
        b1 = sum(a - b for a, b in zip(ys[:h], xs[:h])) / h
        b2 = sum(a - b for a, b in zip(ys[h:], xs[h:])) / (n_days - h)
        bias_shift = b2 - b1
        drift_flag = abs(bias_shift) > max(2.0, 0.25 * mx)
    else:
        slope = intercept = r2 = rmse = mae = bias = nrmse = bias_shift = None
        drift_flag = False

    checks = {
        "completeness_ge_75pct": completeness >= 0.75,
        "r2_ge_0_70": r2 is not None and r2 >= 0.70,
        "slope_within_0_65_1_35": (
            slope is not None and 0.65 - 1e-6 <= slope <= 1.35 + 1e-6),
        "intercept_within_pm5": (
            intercept is not None and -5 - 1e-6 <= intercept <= 5 + 1e-6),
        "rmse_le_7_or_nrmse_le_30pct": bool(
            (rmse is not None and rmse <= 7)
            or (nrmse is not None and nrmse <= 0.30)),
    }
    meets = all(checks.values())

    if n_days < min_days:
        status = "insufficient_evidence"
    elif not meets:
        status = "unfit"
    elif drift_flag:
        status = "drifting"
    else:
        status = "fit"

    return {
        "status": status,
        "standard": STANDARD,
        "n_days": n_days,
        "total_days": total_days,
        "completeness": completeness,
        "daily": {
            "slope": slope, "intercept": intercept, "r2": r2,
            "rmse": rmse, "nrmse": nrmse, "mae": mae, "bias": bias,
            "mean_reference": (sum(d[2] for d in daily) / n_days)
            if n_days else None,
        },
        "epa_checks": checks,
        "meets_epa_targets": meets,
        "drift": {
            "bias_shift": bias_shift, "drift_flag": drift_flag,
            "note": "AeroLoop heuristic (not EPA): |bias shift between "
                    "chronological halves| > max(2.0, 0.25 x mean reference)",
        },
        "hourly": hourly,
    }


def _incumbent_version() -> Optional[str]:
    """Latest non-rejected, non-tabpfn strategy version."""
    import db

    def vnum(v: str) -> int:
        import re
        m = re.match(r"v(\d+)", v)
        return int(m.group(1)) if m else -1

    vs = [s["version"] for s in db.get_strategies()
          if not s["version"].endswith(("-rejected", "-tabpfn"))]
    return max(vs, key=vnum) if vs else None


def trust_report(subject: str = "cams_raw") -> Dict[str, Any]:
    """Trust per laqn:* station for subject in cams_raw|incumbent."""
    import agent
    import db
    import main

    if subject not in ("cams_raw", "incumbent"):
        raise ValueError(f"unknown subject {subject}")

    readings = _reference_hours_all()
    sites = sorted(s for s in {r["station_id"] for r in db.get_readings()}
                   if s.startswith("laqn:"))
    preds_by_site: Dict[str, List[Dict[str, Any]]] = {}
    for p in db.get_predictions():
        if p["station_id"].startswith("laqn:"):
            preds_by_site.setdefault(p["station_id"], []).append(p)

    incumbent = _incumbent_version() if subject == "incumbent" else None
    report = {"subject": subject, "standard": STANDARD, "sites": {}}
    if subject == "incumbent":
        report["incumbent_version"] = incumbent
        report["window"] = "holdout"

    for site in sites:
        truth = readings.get(site, {})
        triples: List[Triple] = []
        for p in preds_by_site.get(site, []):
            ref = truth.get(p["timestamp"])
            if ref is None:
                continue
            inputs = p["inputs"] if isinstance(p["inputs"], dict) else \
                __import__("json").loads(p["inputs"])
            if subject == "cams_raw":
                sv = inputs.get("pm25_model")
            else:
                kind, params = main._resolve_strategy(incumbent)
                sv = main._run_strategy(kind, params, inputs)
            if sv is None:
                continue
            triples.append((p["timestamp"], sv, ref))

        if subject == "incumbent":
            # holdout only: the incumbent was tuned on the tune split
            _, holdout = agent._split(
                [{"timestamp": t[0], "s": t[1], "r": t[2]} for t in triples])
            triples = [(m["timestamp"], m["s"], m["r"]) for m in holdout]

        res = score_triples(triples)
        report["sites"][site] = res
    return report


def _reference_hours_all() -> Dict[str, Dict[str, float]]:
    import db

    out: Dict[str, Dict[str, float]] = {}
    for r in db.get_readings():
        out.setdefault(r["station_id"], {})[r["timestamp"]] = r["measured_pm25"]
    return out
