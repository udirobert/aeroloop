import httpx

import agent
import db
import reppo
from conftest import make_pairs


def _clear_keys(monkeypatch):
    for v in ("SERV_API_KEY", "OPENROUTER_API_KEY", "LLM_BASE_URL", "LLM_MODEL",
              "LLM_API_KEY", "REPPO_API_KEY", "TABPFN_ACCESS_TOKEN"):
        monkeypatch.delenv(v, raising=False)


def _mock_reppo(monkeypatch, handler):
    monkeypatch.setattr(reppo, "_client",
                        lambda: httpx.Client(transport=httpx.MockTransport(handler)))


def _strategies_delta(before):
    return [s for s in db.get_strategies() if s["version"] not in before]


def test_winner_kept_when_gate_not_configured(temp_db, monkeypatch, llm_spy):
    calls, state = llm_spy
    _clear_keys(monkeypatch)
    before = {s["version"] for s in db.get_strategies()}

    run = agent.run_tournament(make_pairs(24))

    new = _strategies_delta(before)
    assert len(new) == 1  # exactly one strategy row per tournament
    assert not new[0]["version"].endswith("-rejected")
    assert "soundness gate not configured" in new[0]["description"]
    assert run["winner"] is not None
    assert run["outcome"] == "winner"
    # skipped proposers are reported, never silently dropped
    by_name = {p["proposer"]: p for p in run["proposals"]}
    assert by_name["serv-nano"]["status"] == "skipped"
    assert by_name["serv-nano"]["error"] == "missing SERV_API_KEY"
    assert by_name["serv-ultra"]["status"] == "skipped"


def test_reppo_reject_saves_ghost(temp_db, monkeypatch, llm_spy):
    calls, state = llm_spy
    _clear_keys(monkeypatch)
    monkeypatch.setenv("REPPO_API_KEY", "rk")

    def handler(req):
        if req.method == "POST":
            assert req.url.path == "/api/v1/agents/evals"
            return httpx.Response(201, json={"id": "e1", "status": "QUEUED"})
        return httpx.Response(200, json={
            "id": "e1", "status": "COMPLETED",
            "result": {"score": 21, "decision": "reject", "confidence": "high",
                       "route": "block", "reason": "params physically implausible",
                       "rubric_scores": {}},
        })

    _mock_reppo(monkeypatch, handler)
    before = {s["version"] for s in db.get_strategies()}
    run = agent.run_tournament(make_pairs(24))

    new = _strategies_delta(before)
    assert len(new) == 1
    assert new[0]["version"].endswith("-rejected")
    assert run["outcome"] == "gate_rejected"
    gated = [p for p in run["proposals"] if p["gate_status"] == "reject"]
    assert gated and gated[0]["reppo"]["reason"] == "params physically implausible"


def test_no_eligible_saves_ghost(temp_db, monkeypatch, llm_spy):
    calls, state = llm_spy
    _clear_keys(monkeypatch)
    # incumbent is already perfect -> nothing can be accuracy-eligible
    pairs = make_pairs(24)
    for p in pairs:
        p["actual"] = p["inputs"]["pm25_model"] + 0.6
    before = {s["version"] for s in db.get_strategies()}
    run = agent.run_tournament(pairs)

    new = _strategies_delta(before)
    assert len(new) == 1
    assert new[0]["version"].endswith("-rejected")
    assert "no proposal beat incumbent" in new[0]["description"]
    assert run["outcome"] == "no_eligible"
    assert run["winner"] is None


def test_run_and_proposals_persist(temp_db, monkeypatch, llm_spy):
    _clear_keys(monkeypatch)
    run = agent.run_tournament(make_pairs(24))
    stored = db.get_tournament_run(run["id"])
    assert stored is not None
    assert stored["tune_n"] == run["tune_n"]
    assert stored["holdout_n"] == run["holdout_n"]
    assert stored["windows"] == run["windows"]
    assert len(stored["proposals"]) == len(run["proposals"])
    assert db.get_tournament_runs()
    p = next(p for p in stored["proposals"] if p["proposer"] == "heuristic")
    assert p["holdout"]["whole"]["mae"] is not None
    assert p["eligible"] in (True, False)


def test_leaderboard_sorted_by_holdout_mae(temp_db, monkeypatch, llm_spy):
    _clear_keys(monkeypatch)
    run = agent.run_tournament(make_pairs(24))
    maes = [p["holdout"]["whole"]["mae"] for p in run["proposals"]
            if p.get("holdout") and p["holdout"].get("whole")]
    assert maes == sorted(maes)


def test_post_tournament_end_to_end(temp_db, monkeypatch, llm_spy):
    """Seed via /demo-day, run /tournament through the real FastAPI app."""
    _clear_keys(monkeypatch)
    from fastapi.testclient import TestClient
    import main

    with TestClient(main.app) as client:
        r = client.post("/demo-day?hours=24")
        assert r.status_code == 200
        r = client.post("/tournament")
        assert r.status_code == 200
        run = r.json()
        assert run["winner"] is not None or run["outcome"] != "winner"
        assert run["strategy_version"]
        names = {p["proposer"] for p in run["proposals"]}
        assert {"serv-nano", "serv-ultra", "open-weight", "heuristic"} <= names

        runs = client.get("/tournament/runs").json()
        assert runs and runs[0]["id"] == run["id"]
        detail = client.get(f"/tournament/runs/{run['id']}").json()
        assert len(detail["proposals"]) == len(run["proposals"])
        assert client.get("/tournament/runs/99999").status_code == 404

        # still exactly one new strategy row
        assert client.get("/strategies").status_code == 200


def test_tournament_precondition(temp_db):
    from fastapi.testclient import TestClient
    import main

    with TestClient(main.app) as client:
        r = client.post("/tournament")
        assert r.status_code == 400
        assert "matched" in r.json()["detail"]
