"""Score every strategy on the real-reference audit's chronological holdout.

Per-site and overall scores; the station list comes from the DB, so this works
on the single-site audit DB and the multi-site one alike.

    python score_real_audit.py [--out submission/evidence/real-audit.json]
"""
import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.environ.setdefault("DATABASE_PATH", "../data/aeroloop-laqn.db")

import agent  # noqa: E402
import db  # noqa: E402
import evaluation  # noqa: E402
import main  # noqa: E402


def score(version, subset):
    kind, params = main._resolve_strategy(version)
    norm = [{"station_id": m["station_id"], "timestamp": m["timestamp"],
             "predicted_pm25": main._run_strategy(kind, params, m["inputs"])}
            for m in subset]
    truth = [{"station_id": m["station_id"], "timestamp": m["timestamp"],
              "measured_pm25": m["actual"]} for m in subset]
    r = evaluation.evaluate(norm, truth)
    return {k: r[k] for k in ("n", "mae", "rmse", "bias")}


def site_scores(site_pairs, strategies):
    tune, holdout = agent._split(site_pairs)
    out = {
        "pairs": len(site_pairs), "tune_n": len(tune), "holdout_n": len(holdout),
    }
    if site_pairs:
        out["window"] = [site_pairs[0]["timestamp"], site_pairs[-1]["timestamp"]]
    if holdout:
        out["holdout_window"] = [holdout[0]["timestamp"],
                                 holdout[-1]["timestamp"]]
    out["strategies"] = {}
    for v in strategies:
        out["strategies"][v] = {"whole": score(v, site_pairs),
                                "holdout": score(v, holdout)}
    return out


def run() -> dict:
    db.init_db()
    pairs = main._matched_pairs()
    strategies = [s["version"] for s in db.get_strategies()]

    by_site = {}
    for m in pairs:
        by_site.setdefault(m["station_id"], []).append(m)

    out = {
        "stations": sorted(by_site),
        "pairs": len(pairs),
        "sites": {s: site_scores(ps, strategies)
                  for s, ps in sorted(by_site.items())},
        "overall": site_scores(pairs, strategies),
    }
    if pairs:
        out["measured_range"] = [min(m["actual"] for m in pairs),
                                 max(m["actual"] for m in pairs)]
    return out


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=None, help="write JSON to this path")
    a = ap.parse_args()
    out = run()
    text = json.dumps(out, indent=1)
    if a.out:
        os.makedirs(os.path.dirname(a.out) or ".", exist_ok=True)
        with open(a.out, "w") as f:
            f.write(text + "\n")
        print(f"wrote {a.out}")
    print(text)
