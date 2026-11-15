"""Score every strategy on the real-reference audit's chronological holdout."""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.environ.setdefault("DATABASE_PATH", "../data/aeroloop-laqn.db")

import agent  # noqa: E402
import db  # noqa: E402
import evaluation  # noqa: E402
import main  # noqa: E402

db.init_db()
pairs = main._matched_pairs()
tune, holdout = agent._split(pairs)
strategies = {s["version"]: s for s in db.get_strategies()}


def score(version, subset):
    kind, params = main._resolve_strategy(version)
    norm = [{"station_id": m["station_id"], "timestamp": m["timestamp"],
             "predicted_pm25": main._run_strategy(kind, params, m["inputs"])}
            for m in subset]
    truth = [{"station_id": m["station_id"], "timestamp": m["timestamp"],
              "measured_pm25": m["actual"]} for m in subset]
    r = evaluation.evaluate(norm, truth)
    return {k: r[k] for k in ("n", "mae", "rmse", "bias")}


out = {
    "station": "north_kensington (LAQN KC1)",
    "truth_source": "LAQN KC1 ratified reference PM2.5",
    "window": [pairs[0]["timestamp"], pairs[-1]["timestamp"]],
    "pairs": len(pairs), "tune_n": len(tune), "holdout_n": len(holdout),
    "holdout_window": [holdout[0]["timestamp"], holdout[-1]["timestamp"]],
    "measured_range": [min(m["actual"] for m in pairs), max(m["actual"] for m in pairs)],
    "strategies": {},
}
for v in strategies:
    out["strategies"][v] = {"whole": score(v, pairs), "holdout": score(v, holdout)}
print(json.dumps(out, indent=1))
