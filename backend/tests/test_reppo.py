import httpx

import reppo


def _client(handler):
    return httpx.Client(transport=httpx.MockTransport(handler))


def test_not_configured(monkeypatch):
    monkeypatch.delenv("REPPO_API_KEY", raising=False)
    g = reppo.run_gate("input text")
    assert g["status"] == "not_configured"


def test_queued_then_completed_accept(monkeypatch):
    monkeypatch.setenv("REPPO_API_KEY", "rk")
    polls = {"n": 0}

    def handler(req):
        if req.method == "POST":
            assert req.headers["Authorization"] == "Bearer rk"
            return httpx.Response(201, json={"id": "e1", "status": "QUEUED", "error": None})
        polls["n"] += 1
        if polls["n"] == 1:
            return httpx.Response(200, json={"id": "e1", "status": "QUEUED", "error": None})
        return httpx.Response(200, json={
            "id": "e1", "status": "COMPLETED", "error": None,
            "result": {"score": 82, "decision": "accept", "confidence": "high",
                       "route": "ship", "reason": "sound", "rubric_scores": {"a": 1}},
        })

    g = reppo.run_gate("input", poll_interval_s=0, client=_client(handler))
    assert g["status"] == "accept"
    assert g["reppo"]["id"] == "e1"
    assert g["reppo"]["score"] == 82
    assert g["reppo"]["confidence"] == "high"


def test_completed_reject_decision(monkeypatch):
    monkeypatch.setenv("REPPO_API_KEY", "rk")

    def handler(req):
        if req.method == "POST":
            return httpx.Response(201, json={"id": "e2", "status": "QUEUED"})
        return httpx.Response(200, json={
            "id": "e2", "status": "COMPLETED",
            "result": {"score": 30, "decision": "reject", "confidence": "medium",
                       "route": "block", "reason": "implausible", "rubric_scores": {}},
        })

    g = reppo.run_gate("input", poll_interval_s=0, client=_client(handler))
    assert g["status"] == "reject"
    assert g["reppo"]["decision"] == "reject"


def test_failed_eval(monkeypatch):
    monkeypatch.setenv("REPPO_API_KEY", "rk")

    def handler(req):
        if req.method == "POST":
            return httpx.Response(201, json={"id": "e3", "status": "QUEUED"})
        return httpx.Response(200, json={"id": "e3", "status": "FAILED"})

    g = reppo.run_gate("input", poll_interval_s=0, client=_client(handler))
    assert g["status"] == "failed"


def test_timeout(monkeypatch):
    monkeypatch.setenv("REPPO_API_KEY", "rk")

    def handler(req):
        if req.method == "POST":
            return httpx.Response(201, json={"id": "e4", "status": "QUEUED"})
        return httpx.Response(200, json={"id": "e4", "status": "QUEUED"})

    g = reppo.run_gate("input", timeout_s=0.01, poll_interval_s=0,
                       client=_client(handler))
    assert g["status"] == "timeout"


def test_402_submit_is_error(monkeypatch):
    monkeypatch.setenv("REPPO_API_KEY", "rk")

    def handler(req):
        return httpx.Response(402, json={"error": "insufficient credits"})

    g = reppo.run_gate("input", poll_interval_s=0, client=_client(handler))
    assert g["status"] == "error"
    assert "402" in g["reppo"]["error"]
