import agent
from conftest import make_pairs


def _pairs_with_ts(n):
    return [{"timestamp": f"2026-01-{i + 1:02d}T00:00:00", "x": i} for i in range(n)]


def test_windows_chronological_and_cover_holdout():
    holdout = _pairs_with_ts(10)
    ws = agent.holdout_windows(holdout, k=3)
    assert len(ws) == 3
    assert [p for w in ws for p in w] == holdout  # order preserved, nothing dropped
    assert all(len(w) >= 2 for w in ws)


def test_windows_reduced_when_too_small():
    holdout = _pairs_with_ts(5)
    ws = agent.holdout_windows(holdout, k=3)
    # 5 // 3 == 1 < 2 -> reduced to 2 windows (>=2 each)
    assert len(ws) == 2
    assert all(len(w) >= 2 for w in ws)


def test_windows_min_one():
    ws = agent.holdout_windows(_pairs_with_ts(2), k=3)
    assert len(ws) == 1
    assert len(ws[0]) == 2


def test_windows_empty_holdout():
    assert agent.holdout_windows([], k=3) == []


def test_eligibility_requires_better_and_majority(temp_db, monkeypatch, llm_spy):
    """Eligible iff whole-holdout MAE < incumbent's AND > K/2 windows won."""
    calls, state = llm_spy
    monkeypatch.delenv("SERV_API_KEY", raising=False)
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    monkeypatch.delenv("LLM_API_KEY", raising=False)
    monkeypatch.delenv("REPPO_API_KEY", raising=False)

    run = agent.run_tournament(make_pairs(24))
    by_name = {p["proposer"]: p for p in run["proposals"]}

    # heuristic adjusts bias downward toward the true +1.5 offset: eligible
    assert by_name["heuristic"]["eligible"] is True
    assert by_name["heuristic"]["windows_won"] > run["windows"] / 2
    # llm mock proposes bias=-1 -> strictly worse than incumbent everywhere
    ow = by_name["open-weight"]
    assert ow["eligible"] is False
    assert ow["windows_won"] == 0


def test_tie_in_windows_is_not_strict_majority(temp_db, monkeypatch, llm_spy):
    """A proposal that only ties the incumbent cannot win a strict majority."""
    calls, state = llm_spy
    # identical params to incumbent -> same MAE, wins 0 windows, never eligible
    state["content"] = (
        '{"what_went_wrong":"x","pattern_discovered":"y","change_made":"z",'
        '"why_it_should_help":"w","proposed_params":{"humidity_coef":-0.05,'
        '"wind_coef":-0.3,"precip_coef":-0.5,"bias":2.0}}'
    )
    monkeypatch.delenv("SERV_API_KEY", raising=False)
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    monkeypatch.delenv("LLM_API_KEY", raising=False)
    monkeypatch.delenv("REPPO_API_KEY", raising=False)

    # actuals chosen so incumbent is exactly right -> nothing can beat it
    pairs = make_pairs(24)
    for p in pairs:
        p["actual"] = p["inputs"]["pm25_model"] + 0.6  # incumbent pred offset
    run = agent.run_tournament(pairs)
    assert all(not p["eligible"] for p in run["proposals"])
    assert run["outcome"] == "no_eligible"
