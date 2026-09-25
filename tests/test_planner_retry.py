"""The planner asks twice when the reply is unusable.

Measured on 2026-09-25 with the profile bench (10 missions, two token budgets): one planner call in
ten came back **empty** from NVIDIA's GLM endpoint, at the same rate with 1024 and with 2048 tokens.
Not a truncation, so a bigger budget is not the fix; a second question is. These tests pin that:
one retry for an unusable reply, no retry for a connection failure (the HTTP layer already spends
its three attempts on that), and the original error when both replies are unusable.
"""


import pytest

from jev_ultrafast import model

PLAN = '{"steps": ["Type Zurich into Where from?", "Click Search"]}'
PAGE = {"url": "https://example.test/", "title": "Search", "text": "Search", "scroll": {"y": 0}, "actions": []}


@pytest.fixture
def planner(monkeypatch):
    for name in ("POLICY_PROVIDER", "TEXT_MODEL_PROVIDER"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("PLANNER_PROVIDER", "nvidia")
    monkeypatch.setenv("PLANNER_MODEL", "z-ai/glm-5.3")
    monkeypatch.setenv("NVIDIA_API_KEY", "nvapi_test")
    return monkeypatch


def replies(monkeypatch, *contents):
    """Answer each planner request with the next canned content; record the calls."""
    calls = []

    def fake_chat(_provider, _system, user, max_tokens=1024):
        calls.append({"user": user, "max_tokens": max_tokens})
        content = contents[min(len(calls) - 1, len(contents) - 1)]
        return content, {"model": "glm", "usage": {}}

    monkeypatch.setattr(model.providers, "chat", fake_chat)
    return calls


def test_an_empty_reply_is_asked_again(planner):
    calls = replies(planner, "", PLAN)
    assert model.plan_steps("Find a flight", PAGE) == ["Type Zurich into Where from?", "Click Search"]
    assert len(calls) == 2, "an empty planning reply must be asked again"
    assert calls[0]["max_tokens"] == calls[1]["max_tokens"] == 1024, "same question, same budget"


def test_a_malformed_reply_is_asked_again(planner):
    calls = replies(planner, '{"steps": []}', PLAN)
    assert model.plan_steps("Find a flight", PAGE) == ["Type Zurich into Where from?", "Click Search"]
    assert len(calls) == 2


def test_two_unusable_replies_still_raise(planner):
    """The agent already degrades gracefully; the planner must not invent a plan instead."""
    calls = replies(planner, "", "")
    with pytest.raises(ValueError):
        model.plan_steps("Find a flight", PAGE)
    assert len(calls) == model.PLANNER_ATTEMPTS == 2, "two questions, no more"


def test_a_connection_failure_is_not_asked_again(planner):
    """model.post_json already spends three attempts on the wire; asking a fourth time is noise."""
    calls = []

    def broken(*_args, **_kwargs):
        calls.append(1)
        raise RuntimeError("Model connection failed; no action executed — no answer within 60 s.")

    planner.setattr(model.providers, "chat", broken)
    with pytest.raises(RuntimeError) as failure:
        model.plan_steps("Find a flight", PAGE)
    assert len(calls) == 1
    assert "no answer within 60 s" in str(failure.value), "the real cause reaches the caller"


def test_a_good_reply_is_asked_once(planner):
    calls = replies(planner, PLAN)
    assert model.plan_steps("Find a flight", PAGE)
    assert len(calls) == 1, "no retry when the first answer is usable"


def test_replanning_gets_the_same_second_chance(planner):
    calls = replies(planner, "", PLAN)
    steps = model.replan_steps(
        "Find a flight", ["Open the site", "Search"], 1, "the search button did nothing", PAGE, []
    )
    assert steps == ["Type Zurich into Where from?", "Click Search"]
    assert len(calls) == 2
    assert "PROBLEM: the search button did nothing" in calls[0]["user"]
