"""The agent waits for slow, free endpoints — and says which failure it was.

On 2026-09-25 the sidebar showed the planner and the executor red with *"Model connection
failed; no action executed."* while the text role, on the very same NVIDIA NIM key, answered
after 37.8 s. The key was fine: three 25 s attempts had gone by without a single byte, which
is a free tier waking up, not a rejected key. These tests pin the two things that fix that:
the wait is long enough to survive a cold start (and can be raised with JEV_HTTP_TIMEOUT),
and the error a user reads distinguishes "nobody answered" from "your key was rejected".
"""

from unittest.mock import Mock

import httpx
import pytest

from jev_ultrafast import model, providers


@pytest.fixture
def no_sleep(monkeypatch):
    monkeypatch.setattr(model.time, "sleep", lambda _seconds: None)


def fake_client(post):
    return Mock(post=post)


# ── how long to wait ─────────────────────────────────────────────────────────


def test_the_default_wait_survives_a_cold_start(monkeypatch):
    """25 s was measured as too short; the default is minutes-free but patient."""
    monkeypatch.delenv("JEV_HTTP_TIMEOUT", raising=False)
    assert model.timeout_seconds() == model.DEFAULT_TIMEOUT
    assert model.DEFAULT_TIMEOUT >= 45, "a free endpoint that has to wake up needs longer than 25 s"


def test_the_wait_can_be_raised_or_lowered(monkeypatch):
    monkeypatch.setenv("JEV_HTTP_TIMEOUT", "120")
    assert model.timeout_seconds() == 120
    monkeypatch.setenv("JEV_HTTP_TIMEOUT", "10.5")
    assert model.timeout_seconds() == 10.5


@pytest.mark.parametrize("value", ["", "  ", "soon", "0", "-5"])
def test_a_useless_value_falls_back_to_the_default(monkeypatch, value):
    monkeypatch.setenv("JEV_HTTP_TIMEOUT", value)
    assert model.timeout_seconds() == model.DEFAULT_TIMEOUT


def test_the_shared_client_follows_the_environment(monkeypatch):
    """The client is built on first use, so a JEV_HTTP_TIMEOUT that arrived with the key file
    counts even though this module was imported long before the key file was read."""
    monkeypatch.setenv("JEV_HTTP_TIMEOUT", "31")
    assert model.CLIENT.timeout.read == 31.0
    monkeypatch.setenv("JEV_HTTP_TIMEOUT", "17")
    assert model.CLIENT.timeout.read == 17.0, "the setting is re-read, not frozen at import"


def test_a_second_client_picks_the_configured_wait(monkeypatch):
    monkeypatch.setenv("JEV_HTTP_TIMEOUT", "90")
    assert model.build_client().timeout.read == 90.0
    monkeypatch.setenv("JEV_HTTP_TIMEOUT", "90")
    assert model.build_client().timeout.connect == 15.0, "connecting stays quick"


# ── what the user reads when nothing comes back ──────────────────────────────


def test_a_stall_is_reported_as_a_slow_endpoint_not_a_bad_key(monkeypatch, no_sleep):
    calls = []

    def stalled(*_args, **_kwargs):
        calls.append(1)
        raise httpx.ReadTimeout("timed out")

    monkeypatch.setattr(model, "CLIENT", fake_client(stalled))
    with pytest.raises(RuntimeError) as failure:
        model.post_json("https://example.test/v1/chat/completions", "key", {})
    message = str(failure.value)
    assert "Model connection failed; no action executed" in message, "the old wording still reads true"
    assert "not a rejected key" in message, "the user must not go looking for a new key"
    assert "JEV_HTTP_TIMEOUT" in message, "and the knob to wait longer is named"
    assert len(calls) == model.ATTEMPTS, "a stall is retried before it is given up on"


def test_an_unreachable_host_says_network_not_key(monkeypatch, no_sleep):
    def refused(*_args, **_kwargs):
        raise httpx.ConnectError("connection refused")

    monkeypatch.setattr(model, "CLIENT", fake_client(refused))
    with pytest.raises(RuntimeError) as failure:
        model.post_json("https://example.test/v1/chat/completions", "key", {})
    message = str(failure.value)
    assert "Model connection failed; no action executed" in message
    assert "proxy or a VPN" in message
    assert "not a rejected key" not in message, "a refused connection is not the same story"


def test_a_rejected_key_still_comes_back_as_a_key_problem(monkeypatch, no_sleep):
    """The distinction only helps if a real 401 keeps saying HTTP 401."""
    response = Mock(status_code=401, is_error=True, text='{"error":"Invalid API Key"}')

    def unauthorized(*_args, **_kwargs):
        return response

    monkeypatch.setattr(model, "CLIENT", fake_client(unauthorized))
    with pytest.raises(RuntimeError) as failure:
        model.post_json("https://example.test/v1/chat/completions", "bad-key", {})
    message = str(failure.value)
    assert "HTTP 401" in message and "Invalid API Key" in message
    assert "no answer within" not in message


def test_the_stream_path_waits_the_same_way(monkeypatch, no_sleep):
    """A stream that never produced a byte is the same story as a stalled request."""
    calls = []

    def stalled(*_args, **_kwargs):
        calls.append(1)
        raise httpx.ReadTimeout("timed out")

    monkeypatch.setattr(model, "CLIENT", Mock(stream=stalled))
    with pytest.raises(RuntimeError) as failure:
        model.post_stream("https://example.test/v1/chat/completions", "key", {})
    assert "not a rejected key" in str(failure.value)
    assert len(calls) == model.ATTEMPTS


# ── the check tells the sidebar which role it is asking ──────────────────────


def test_the_check_reports_every_role_as_it_goes(monkeypatch):
    """The wait is visible: start and result per role, and never a key."""
    for name in ("POLICY_PROVIDER", "PLANNER_PROVIDER", "TEXT_MODEL_PROVIDER", "TYPESAFE_API_KEY"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("GROQ_API_KEY", "gsk_secret_value")

    def fake_chat(provider, system, user, max_tokens=1024):
        if provider["model"] == "openai/gpt-oss-120b":
            raise RuntimeError("Model connection failed; no action executed — no answer within 60 s.")
        return "{}", {"model": provider["model"], "usage": {}, "provider": provider["name"]}

    monkeypatch.setattr(providers, "chat", fake_chat)
    from jev_ultrafast import firefox

    events = []
    results = firefox.check_providers(lambda kind, payload: events.append((kind, payload)))

    assert [kind for kind, _ in events] == ["start", "done"] * len(results)
    started = [payload for kind, payload in events if kind == "start"]
    assert {payload["role"] for payload in started} == set(results)
    assert all(payload["model"] for payload in started), "the sidebar is told which model it is asking"
    done = {payload["role"]: payload for kind, payload in events if kind == "done"}
    assert done["planner"]["ok"] is False and "no answer within 60 s" in done["planner"]["detail"]
    assert done["policy"]["ok"] is True
    assert "gsk_secret_value" not in repr(events), "progress never carries the key"


def test_progress_is_optional_and_never_breaks_the_check(monkeypatch):
    """A caller that passes no callback (scripts, tests) gets the same report as before."""
    monkeypatch.setenv("GROQ_API_KEY", "gsk")
    monkeypatch.setattr(providers, "chat", Mock(return_value=("{}", {})))
    from jev_ultrafast import firefox

    assert firefox.check_providers()["policy"]["ok"] is True

    def rude(_kind, _payload):
        raise RuntimeError("the sidebar hung up")

    assert firefox.check_providers(rude)["policy"]["ok"] is True, "progress is a courtesy, not a contract"
