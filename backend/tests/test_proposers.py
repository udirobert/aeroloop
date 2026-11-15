import json

import agent
from conftest import good_llm_json, make_pairs


def test_missing_key_proposer_is_skipped(temp_db, monkeypatch):
    monkeypatch.delenv("SERV_API_KEY", raising=False)
    cfg = next(c for c in agent.load_proposers() if c["name"] == "serv-nano")
    resolved, reason = agent.resolve_proposer(cfg)
    assert resolved is None
    assert reason == "missing SERV_API_KEY"


def test_disabled_proposer_is_skipped(temp_db):
    resolved, reason = agent.resolve_proposer({"name": "x", "enabled": False})
    assert resolved is None
    assert reason == "disabled in proposers.json"


def test_env_referenced_resolution(temp_db, monkeypatch):
    monkeypatch.setenv("LLM_BASE_URL", "https://router.huggingface.co/v1")
    monkeypatch.setenv("LLM_MODEL", "google/gemma-3-27b-it")
    monkeypatch.setenv("LLM_API_KEY", "hf_test")
    cfg = next(c for c in agent.load_proposers() if c["name"] == "open-weight")
    resolved, reason = agent.resolve_proposer(cfg)
    assert reason is None
    assert resolved["base_url"] == "https://router.huggingface.co/v1"
    assert resolved["model"] == "google/gemma-3-27b-it"
    assert resolved["api_key"] == "hf_test"


def test_env_defaults_when_unset(temp_db, monkeypatch):
    for v in ("LLM_BASE_URL", "LLM_MODEL", "LLM_API_KEY"):
        monkeypatch.delenv(v, raising=False)
    cfg = next(c for c in agent.load_proposers() if c["name"] == "open-weight")
    resolved, reason = agent.resolve_proposer(cfg)
    # open-weight carries ollama defaults so local setups still run
    assert reason is None
    assert resolved["base_url"] == "http://localhost:11434/v1"
    assert resolved["model"] == "nemotron-mini:latest"


def test_all_llm_proposers_get_identical_messages_with_system(
    temp_db, monkeypatch, llm_spy
):
    calls, _ = llm_spy
    monkeypatch.setenv("SERV_API_KEY", "k1")
    monkeypatch.setenv("OPENROUTER_API_KEY", "k2")
    monkeypatch.delenv("REPPO_API_KEY", raising=False)

    agent.run_tournament(make_pairs(24))

    assert len(calls) >= 3  # serv-nano, serv-ultra, open-weight
    first = calls[0]["messages"]
    assert first[0]["role"] == "system"  # SERV 400s without a system message
    assert first[1]["role"] == "user"
    for c in calls[1:]:
        assert c["messages"] == first  # byte-identical across proposers


def test_prompt_has_no_holdout_leakage(temp_db):
    pairs = make_pairs(24)
    tune, holdout = agent._split(pairs)
    incumbent_version, incumbent_params = agent._incumbent()
    tune_errors = agent._errors_for(incumbent_params, tune)
    system, user = agent.build_messages(tune_errors, incumbent_params)
    text = system + user
    holdout_ts = {h["timestamp"] for h in holdout}
    tune_ts = {t["timestamp"] for t in tune}
    assert not holdout_ts & tune_ts  # sanity: splits are disjoint
    for h in holdout:
        assert h["timestamp"] not in text


def test_cost_computed_from_usage_and_prices(temp_db, llm_spy):
    calls, _ = llm_spy
    r = agent.call_llm("https://x", "m", "k", [{"role": "user", "content": "hi"}],
                       price_in=0.13, price_out=0.65)
    assert r["status"] == "ok"
    assert r["prompt_tokens"] == 100
    assert r["completion_tokens"] == 40
    assert abs(r["cost_usd"] - (100 * 0.13 + 40 * 0.65) / 1e6) < 1e-9


def test_cost_none_when_prices_null(temp_db, llm_spy):
    r = agent.call_llm("https://x", "m", "k", [{"role": "user", "content": "hi"}])
    assert r["status"] == "ok"
    assert r["cost_usd"] is None


def test_no_params_status(temp_db, monkeypatch):
    import agent as ag
    calls = []
    from conftest import FakeOpenAI
    monkeypatch.setattr(ag, "_client", lambda b, k: FakeOpenAI(
        json.dumps({"what_went_wrong": "x", "pattern_discovered": "y",
                    "change_made": "z", "why_it_should_help": "w"}),
        calls, base_url=b, api_key=k))
    r = ag.call_llm("https://x", "m", "k", [{"role": "user", "content": "hi"}])
    assert r["status"] == "no_params"
    assert r["params"] is None
    assert r["analysis"]["what_went_wrong"] == "x"


def test_analyse_errors_still_works_via_shared_messages(temp_db, llm_spy):
    calls, _ = llm_spy
    pairs = make_pairs(24)
    tune, _ = agent._split(pairs)
    errs = agent._errors_for({"bias": 2.0}, tune)
    analysis, params, model = agent.analyse_errors(errs, {"bias": 2.0})
    assert params is not None
    assert calls and calls[0]["messages"][0]["role"] == "system"
    assert good_llm_json(-1.0) is not None


def test_content_filter_refusal_is_named_not_hidden(temp_db, monkeypatch):
    """SERV intermittently refuses benign prompts; the record must say so."""
    from conftest import FakeOpenAI, FakeResponse

    class Refusing(FakeOpenAI):
        def __init__(self, *a, **kw):
            super().__init__(*a, **kw)
            self.chat.completions.create = lambda **k: FakeResponse(
                "I can't share that.", finish_reason="content_filter")

    monkeypatch.setattr(agent, "_client", lambda b, k: Refusing("", []))
    r = agent.call_llm("https://x", "serv-ultra", "k",
                       [{"role": "system", "content": "s"},
                        {"role": "user", "content": "u"}])
    assert r["status"] == "error"
    assert r["finish_reason"] == "content_filter"
    assert "content filter" in r["error"]
    assert r["params"] is None


def test_params_recognised_by_content_not_by_key_name(temp_db):
    """SERV renames the params object between runs and echoes a decoy."""
    parsed = {
        "error_analysis": {"what_went_wrong": "under-reads the monitor"},
        "current_params": {"bias": 99.0},
        "parameter_adjustments": {"bias": -3.5, "humidity_coef": 0.1},
    }
    analysis, params = agent._canonical_analysis(parsed)
    assert params["bias"] == -3.5
    assert analysis["what_went_wrong"] == "under-reads the monitor"


def test_serv_token_param_is_max_completion_tokens(temp_db, monkeypatch, llm_spy):
    calls, _ = llm_spy
    monkeypatch.setenv("SERV_API_KEY", "k")
    cfg = next(c for c in agent.load_proposers() if c["name"] == "serv-nano")
    resolved, reason = agent.resolve_proposer(cfg)
    assert reason is None
    agent.call_llm(resolved["base_url"], resolved["model"], resolved["api_key"],
                   [{"role": "system", "content": "s"}],
                   token_param=resolved["token_param"])
    assert calls[-1]["max_completion_tokens"] == 800
    assert calls[-1]["max_tokens"] is None
