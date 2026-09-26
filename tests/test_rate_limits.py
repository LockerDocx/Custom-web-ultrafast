"""A rate limit is capacity, not a broken key — and the provider says how long to wait."""

import json

import pytest

from jev_ultrafast import model


@pytest.fixture
def clean_env(monkeypatch, tmp_path):
    for name in list(__import__("os").environ):
        prefixes = ("JEV_", "GROQ_", "NVIDIA_", "DEEPSEEK_", "OPENAI_", "POLICY_", "PLANNER_", "TEXT_")
        if name.startswith(prefixes):
            monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("JEV_ENV_FILE", str(tmp_path / "env"))
    return monkeypatch


class FakeClient:
    """A whole stand-in for the shared HTTP client.

    The module says tests replace this object wholesale, and that is not a style choice:
    setting an attribute on the real one (`monkeypatch.setattr(model.CLIENT, "post", …)`)
    leaves a bound method pointing at the client of that moment, `__getattr__` stops
    building, and JEV_HTTP_TIMEOUT is never read again — which is exactly how a stale
    17 s patience leaked into another test's 0.4 s timeout.
    """

    def __init__(self, post=None, stream=None):
        self.post = post or (lambda url, **kwargs: Reply(200, payload={"ok": True}))
        self.stream = stream or (lambda *a, **k: None)


class Reply:
    """The shape httpx gives us just before the provider's own words."""

    def __init__(self, status_code, text="", headers=None, payload=None):
        self.status_code = status_code
        self.text = text
        self.headers = headers or {}
        self._payload = payload
        self.is_error = status_code >= 400

    def json(self):
        return self._payload


GROQ_429 = Reply(
    429,
    '{"error":{"message":"Rate limit reached for model `openai/gpt-oss-20b` ... '
    'Please try again in 1.319999999s. Upgrade to Dev Tier today at https://console.groq.com/settings/billing"}}',
)


def test_the_provider_says_how_long_to_wait():
    # 1.32 s plus a hair of slack: clocks are not in step, and returning early is what caused
    # the original failure (the agent gave up 0.3 s before the provider would have answered).
    assert model.suggested_wait(GROQ_429) == pytest.approx(1.57, abs=0.01)


def test_the_retry_after_header_wins_when_present():
    reply = Reply(429, "rate limited", headers={"retry-after": "2"})
    assert model.suggested_wait(reply) == 2.0


def test_a_long_wait_is_capped_so_the_agent_does_not_go_quiet():
    reply = Reply(429, "Rate limit reached. Please try again in 5 minutes.")
    assert model.suggested_wait(reply) == model.RATE_LIMIT_WAIT_CAP


def test_when_the_provider_says_nothing_there_is_no_invented_number():
    assert model.suggested_wait(Reply(429, "too many requests")) is None


def test_the_agent_waits_the_time_the_provider_asked(clean_env, monkeypatch):
    slept = []
    monkeypatch.setattr(model.time, "sleep", slept.append)
    calls = []

    def post(url, **kwargs):
        calls.append(url)
        return GROQ_429 if len(calls) == 1 else Reply(200, payload={"ok": True})

    monkeypatch.setattr(model, "CLIENT", FakeClient(post=post))
    assert model.post_json("https://api.groq.com/openai/v1/chat/completions", "k", {}) == {"ok": True}
    assert slept == [pytest.approx(1.57, abs=0.01)], "waited what the provider asked, not 0.5 s"


def test_a_reply_that_only_gets_rate_limited_ends_in_a_rate_limit_message(clean_env, monkeypatch):
    monkeypatch.setattr(model.time, "sleep", lambda _s: None)
    monkeypatch.setattr(model, "CLIENT", FakeClient(post=lambda url, **kwargs: GROQ_429))
    with pytest.raises(RuntimeError) as error:
        model.post_json("https://api.groq.com/openai/v1/chat/completions", "k", {})
    message = str(error.value)
    assert "rate limit" in message.lower()
    assert "capacity, not a key problem" in message, "the old wording blamed the key"
    assert "No action was executed." in message
    assert "Please try again in" in message, "the provider's own words stay visible"
    assert "HTTP 429" in message


def test_the_same_rule_applies_to_the_streaming_path(clean_env, monkeypatch):
    slept = []
    monkeypatch.setattr(model.time, "sleep", slept.append)
    calls = []

    class Stream:
        def __init__(self, reply):
            self.reply = reply

        def __enter__(self):
            return self.reply

        def __exit__(self, *exc):
            return False

        def iter_lines(self):
            yield 'data: {"choices":[{"delta":{"content":"hola"}}]}'
            yield "data: [DONE]"

    def stream(method, url, **kwargs):
        calls.append(url)
        reply = GROQ_429 if len(calls) == 1 else Reply(200, "{}")
        reply.iter_lines = lambda: Stream(reply).iter_lines()
        return Stream(reply)

    monkeypatch.setattr(model, "CLIENT", FakeClient(stream=stream))
    text, _usage, _model_id = model.post_stream(
        "https://api.groq.com/openai/v1/chat/completions", "k", {}, on_delta=lambda _d: None
    )
    assert text == "hola"
    assert slept and slept[0] == pytest.approx(1.57, abs=0.01)


def test_rate_limits_are_worth_more_patience_than_a_wire_failure():
    assert model.RATE_LIMIT_ATTEMPTS > model.ATTEMPTS


def test_the_cap_is_short_enough_to_promise():
    assert model.RATE_LIMIT_WAIT_CAP <= 30.0


def test_the_panel_wording_keeps_the_three_failures_apart(clean_env, monkeypatch):
    """Rate limit, no key and a stalled endpoint must not read as the same problem."""
    monkeypatch.setattr(model.time, "sleep", lambda _s: None)
    monkeypatch.setattr(model, "CLIENT", FakeClient(post=lambda url, **kwargs: GROQ_429))
    with pytest.raises(RuntimeError) as limited:
        model.post_json("https://api.groq.com/openai/v1/chat/completions", "k", {})
    message = str(limited.value).lower()
    for wrong in ("api key is wrong", "invalid api key", "unauthorized", "not configured"):
        assert wrong not in message


def test_a_successful_call_is_still_untouched(clean_env, monkeypatch):
    monkeypatch.setattr(model, "CLIENT", FakeClient(post=lambda url, **kwargs: Reply(200, payload={"a": 1})))
    assert model.post_json("https://api.groq.com/openai/v1/chat/completions", "k", {}) == {"a": 1}
    assert json.dumps({"a": 1})
