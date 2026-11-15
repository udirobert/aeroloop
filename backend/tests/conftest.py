import json
import os
import sys
from datetime import datetime, timedelta, timezone

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


@pytest.fixture()
def temp_db(tmp_path, monkeypatch):
    """Point db at a throwaway SQLite file and reload modules that bound it."""
    import db

    monkeypatch.setattr(db, "DB_PATH", str(tmp_path / "test.db"))
    db.init_db()
    return db


def make_pairs(n=24, start=None):
    """Deterministic matched pairs: hourly, chronological, across 2 stations."""
    start = start or datetime(2026, 1, 1, tzinfo=timezone.utc)
    pairs = []
    for i in range(n):
        ts = start + timedelta(hours=i)
        pm = 10.0 + (i % 7)
        pairs.append({
            "station_id": "bloomsbury" if i % 2 == 0 else "marylebone",
            "timestamp": ts.isoformat(),
            "inputs": {
                "pm25_model": pm,
                "no2_model": 20.0,
                "humidity": 60.0,
                "wind_speed": 8.0,
                "temperature": 12.0,
                "precipitation": 0.0,
                "timestamp": ts.isoformat(),
            },
            # actual = pm25_model + a steady bias the incumbent over-shoots
            "actual": pm + 1.5,
        })
    return pairs


class FakeUsage:
    def __init__(self, prompt_tokens=100, completion_tokens=40):
        self.prompt_tokens = prompt_tokens
        self.completion_tokens = completion_tokens


class FakeChoice:
    def __init__(self, content, finish_reason="stop"):
        self.message = type("M", (), {"content": content})()
        self.finish_reason = finish_reason


class FakeResponse:
    def __init__(self, content, usage=None, finish_reason="stop"):
        self.id = "chatcmpl-fake"
        self.choices = [FakeChoice(content, finish_reason)]
        self.usage = usage if usage is not None else FakeUsage()


class FakeCompletions:
    def __init__(self, content_or_fn, calls):
        self._content_or_fn = content_or_fn
        self._calls = calls

    def create(self, model=None, messages=None, temperature=None, max_tokens=None,
               max_completion_tokens=None):
        self._calls.append({
            "model": model,
            "messages": [dict(m) for m in messages],
            "temperature": temperature,
            "max_tokens": max_tokens,
            "max_completion_tokens": max_completion_tokens,
        })
        c = self._content_or_fn
        content = c(model) if callable(c) else c
        return FakeResponse(content)


class FakeOpenAI:
    def __init__(self, content_or_fn, calls, base_url=None, api_key=None):
        self.base_url = base_url
        self.api_key = api_key
        self.chat = type("C", (), {"completions": FakeCompletions(content_or_fn, calls)})()


def good_llm_json(bias=-1.0):
    return json.dumps({
        "what_went_wrong": "systematic over-prediction",
        "pattern_discovered": "positive mean error",
        "change_made": "lowered bias",
        "why_it_should_help": "counters the bias",
        "proposed_params": {"humidity_coef": 0.0, "wind_coef": 0.0,
                            "precip_coef": 0.0, "bias": bias},
    })


@pytest.fixture()
def llm_spy(monkeypatch):
    """Replace agent._client with a recorder. Returns (calls, set_content)."""
    import agent

    calls = []
    state = {"content": good_llm_json()}

    def factory(base_url, api_key):
        return FakeOpenAI(lambda model: state["content"], calls,
                          base_url=base_url, api_key=api_key)

    monkeypatch.setattr(agent, "_client", factory)
    return calls, state
