"""Scale term + OLS heuristic."""
from datetime import datetime, timezone

import agent
import pytest
import prediction


def _feats(pm=10.0):
    return {"pm25_model": pm, "humidity": 60.0, "wind_speed": 8.0,
            "temperature": 12.0, "precipitation": 0.0}


def test_scale_backwards_compatible():
    """Params without 'scale' predict exactly as before."""
    params = {"humidity_coef": -0.05, "wind_coef": -0.3,
              "precip_coef": -0.5, "bias": 2.0}
    without = prediction.improved_v2(_feats(), params)
    explicit = prediction.improved_v2(_feats(), dict(params, scale=1.0))
    assert without == explicit
    doubled = prediction.improved_v2(_feats(), dict(params, scale=2.0))
    assert doubled == pytest.approx(explicit + 10.0)


def test_clamp_defaults_scale_to_one():
    c = agent._clamp({})
    assert c["scale"] == 1.0
    assert agent._clamp({"scale": 0.1})["scale"] == 0.5  # bounds still apply
    assert agent._clamp({"scale": 99})["scale"] == 3.0


def test_ols_heuristic_recovers_known_scale_and_bias():
    """actual = 1.5*pm + 3 (other coefs' contributions zero under incumbent 0s)
    → heuristic should recover scale≈1.5, bias≈3 from tune data only."""
    current = {"scale": 1.0, "humidity_coef": 0.0, "wind_coef": 0.0,
               "precip_coef": 0.0, "bias": 0.0}
    base = datetime(2026, 1, 1, tzinfo=timezone.utc)
    from datetime import timedelta
    errs = []
    for i in range(48):
        pm = 8.0 + (i % 12)
        actual = 1.5 * pm + 3.0
        feats = {"pm25_model": pm, "humidity": 50.0, "wind_speed": 5.0,
                 "precipitation": 0.0}
        pred = prediction.predict("v2-improved", feats, current)
        errs.append({"station_id": "s", "timestamp": (base + timedelta(hours=i)).isoformat(),
                     "inputs": feats, "predicted": pred,
                     "actual": actual, "error": pred - actual})
    p = agent.heuristic_params(current, errs)
    assert p["scale"] == pytest.approx(1.5, abs=0.01)
    assert p["bias"] == pytest.approx(3.0, abs=0.01)


def test_ols_heuristic_uses_incumbent_coefs():
    """When incumbent humidity_coef != 0, its contribution is removed first."""
    current = {"scale": 1.0, "humidity_coef": 0.1, "wind_coef": 0.0,
               "precip_coef": 0.0, "bias": 0.0}
    errs = []
    for i in range(24):
        pm = 10.0 + i
        humidity = 60.0  # incumbent adds 0.1*(60-50)=+1.0
        actual = 1.2 * pm - 1.0  # after removing +1.0 humidity term: bias -2
        feats = {"pm25_model": pm, "humidity": humidity,
                 "wind_speed": 5.0, "precipitation": 0.0}
        errs.append({"station_id": "s", "timestamp": "t", "inputs": feats,
                     "predicted": 0.0, "actual": actual, "error": 0.0})
    p = agent.heuristic_params(current, errs)
    assert p["scale"] == pytest.approx(1.2, abs=0.01)
    assert p["bias"] == pytest.approx(-2.0, abs=0.01)
    assert p["humidity_coef"] == 0.1  # frozen at incumbent value


def test_prompt_mentions_scale():
    assert "scale" in agent.SYSTEM_PROMPT
    assert "scale*pm25_model" in agent.SYSTEM_PROMPT
