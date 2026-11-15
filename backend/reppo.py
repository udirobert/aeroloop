"""Reppo Evaluation API client — the peer "soundness" gate.

Per https://eval.reppo.xyz/agents.md:
  POST {REPPO_BASE_URL}/api/v1/agents/evals  {"taskType":"action","input":"<text>"}
    Authorization: Bearer REPPO_API_KEY  ->  201 {"id",...,"status":"QUEUED"}
  GET  {REPPO_BASE_URL}/api/v1/agents/evals/{id}  ->  poll until COMPLETED|FAILED
  On COMPLETED result = {"score":0-100,"decision":"accept"|"reject",
    "confidence":"low"|"medium"|"high","route":"ship"|"review"|"block",
    "reason":str,"rubric_scores":{...}}

Gate statuses: "accept" (decision accept and route != block), "reject",
"failed", "timeout", "error", "not_configured" (no REPPO_API_KEY).
"""
from __future__ import annotations

import os
import time
from typing import Any, Dict, Optional

import httpx

BASE_URL = os.getenv("REPPO_BASE_URL", "https://eval.reppo.xyz")
POLL_INTERVAL_S = 5.0


def configured() -> bool:
    return bool(os.getenv("REPPO_API_KEY"))


def _client() -> httpx.Client:
    return httpx.Client(timeout=30)


def _base_url() -> str:
    return os.getenv("REPPO_BASE_URL", BASE_URL).rstrip("/")


def submit_eval(input_text: str, client: Optional[httpx.Client] = None) -> Dict[str, Any]:
    """POST an eval. Returns {"id": ...} or {"error": ...}."""
    own = client is None
    client = client or _client()
    try:
        resp = client.post(
            f"{_base_url()}/api/v1/agents/evals",
            json={"taskType": "action", "input": input_text},
            headers={"Authorization": f"Bearer {os.getenv('REPPO_API_KEY')}"},
        )
        if resp.status_code not in (200, 201):
            return {"error": f"submit HTTP {resp.status_code}: {resp.text[:200]}"}
        return resp.json()
    except Exception as e:  # noqa: BLE001 — any transport error -> honest "error" status
        return {"error": f"submit failed: {e!r}"}
    finally:
        if own:
            client.close()


def get_eval(eval_id: str, client: Optional[httpx.Client] = None) -> Dict[str, Any]:
    own = client is None
    client = client or _client()
    try:
        resp = client.get(
            f"{_base_url()}/api/v1/agents/evals/{eval_id}",
            headers={"Authorization": f"Bearer {os.getenv('REPPO_API_KEY')}"},
        )
        if resp.status_code != 200:
            return {"error": f"poll HTTP {resp.status_code}: {resp.text[:200]}"}
        return resp.json()
    except Exception as e:  # noqa: BLE001
        return {"error": f"poll failed: {e!r}"}
    finally:
        if own:
            client.close()


def run_gate(
    input_text: str,
    timeout_s: Optional[float] = None,
    poll_interval_s: float = POLL_INTERVAL_S,
    client: Optional[httpx.Client] = None,
) -> Dict[str, Any]:
    """Submit one eval and poll to a verdict.

    Returns {"status": gate_status, "reppo": {id,status,score,decision,
    confidence,route,reason,rubric_scores,error?}}.
    """
    if not configured():
        return {"status": "not_configured", "reppo": {"id": None}}

    timeout = float(os.getenv("REPPO_TIMEOUT_S", "300")) if timeout_s is None else timeout_s
    own = client is None
    client = client or _client()
    reppo: Dict[str, Any] = {"id": None}
    try:
        submitted = submit_eval(input_text, client=client)
        if "error" in submitted or not submitted.get("id"):
            reppo["error"] = submitted.get("error", "no eval id in response")
            return {"status": "error", "reppo": reppo}
        reppo["id"] = submitted["id"]
        reppo["status"] = submitted.get("status")

        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            ev = get_eval(str(submitted["id"]), client=client)
            if "error" in ev:
                reppo["error"] = ev["error"]
                return {"status": "error", "reppo": reppo}
            status = ev.get("status")
            reppo["status"] = status
            if status == "FAILED":
                return {"status": "failed", "reppo": reppo}
            if status == "COMPLETED":
                result = ev.get("result") or {}
                for k in ("score", "decision", "confidence", "route", "reason", "rubric_scores"):
                    reppo[k] = result.get(k)
                accept = result.get("decision") == "accept" and result.get("route") != "block"
                return {"status": "accept" if accept else "reject", "reppo": reppo}
            if poll_interval_s > 0:
                time.sleep(poll_interval_s)
        return {"status": "timeout", "reppo": reppo}
    finally:
        if own:
            client.close()
