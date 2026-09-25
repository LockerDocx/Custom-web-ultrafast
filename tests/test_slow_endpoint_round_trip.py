"""A real endpoint that is slow: the whole path, over a real socket, with a real clock.

The unit tests above prove what the message says; this proves the behaviour, and it needs no
internet and no key: a local HTTP server that takes its time on purpose stands in for a free
tier that has to wake up. The same call is made twice — patiently, and impatiently — so the
difference between "it waited" and "it gave up" is measured rather than assumed.

Raise the numbers if you ever need to see it by hand: `python -m pytest -s
tests/test_slow_endpoint_round_trip.py` prints the latencies it saw.
"""

import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from jev_ultrafast import model, providers

DELAY = 1.2  # seconds the fake endpoint sleeps before answering


class _SlowEndpoint(BaseHTTPRequestHandler):
    """Answers /v1/chat/completions, but not quickly."""

    delay = DELAY
    calls = []

    def do_POST(self):  # noqa: N802 - the name http.server calls
        length = int(self.headers.get("content-length") or 0)
        self.rfile.read(length)
        type(self).calls.append(time.monotonic())
        time.sleep(type(self).delay)
        body = json.dumps(
            {
                "model": "slow-model",
                "choices": [{"message": {"content": "{}"}}],
                "usage": {"total_tokens": 3},
            }
        ).encode()
        self.send_response(200)
        self.send_header("content-type", "application/json")
        self.send_header("content-length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *_args):  # keep pytest's output clean
        pass


@pytest.fixture
def slow_endpoint():
    """A listening server on a loopback port, for one test."""
    _SlowEndpoint.calls = []
    server = ThreadingHTTPServer(("127.0.0.1", 0), _SlowEndpoint)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_address[1]}/v1"
    finally:
        server.shutdown()
        server.server_close()


@pytest.fixture
def slow_role(monkeypatch, slow_endpoint):
    """Point the executor role at the slow endpoint, the way a user's own gateway would."""
    for name in ("PLANNER_PROVIDER", "PLANNER_BASE_URL", "TEXT_MODEL_PROVIDER", "TEXT_MODEL_BASE_URL"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("POLICY_PROVIDER", "http://127.0.0.1/v1")  # a raw base URL: allowed
    monkeypatch.setenv("POLICY_BASE_URL", slow_endpoint)
    monkeypatch.setenv("POLICY_MODEL", "slow-model")
    monkeypatch.setenv("POLICY_API_KEY", "local")
    return slow_endpoint


def test_the_agent_waits_for_a_slow_endpoint(slow_role, monkeypatch):
    """A 1.2 s answer with a 10 s patience is an answer, and the latency is reported as measured."""
    monkeypatch.setenv("JEV_HTTP_TIMEOUT", "10")
    started = time.monotonic()
    entry = providers.chat(providers.resolve("policy"), "sys", "ping", max_tokens=8)[0]
    waited = time.monotonic() - started
    assert entry is not None
    assert waited >= DELAY, f"the call came back in {waited:.2f} s: it cannot have been answered"
    assert len(_SlowEndpoint.calls) == 1, "one patient attempt, no retries needed"


def test_a_slow_endpoint_that_outlasts_the_patience_says_so(slow_role, monkeypatch):
    """With a shorter patience than the endpoint's own delay the run must not blame the key."""
    monkeypatch.setenv("JEV_HTTP_TIMEOUT", "0.4")
    with pytest.raises(RuntimeError) as failure:
        providers.chat(providers.resolve("policy"), "sys", "ping", max_tokens=8)
    message = str(failure.value)
    assert "no answer within 0.4 s" in message
    assert "not a rejected key" in message
    assert len(_SlowEndpoint.calls) == model.ATTEMPTS, "it must ask more than once before giving up"


def test_the_self_test_reports_a_slow_endpoint_as_working(slow_role, monkeypatch):
    """The sidebar's own check, over the real socket: green, with the measured latency."""
    from jev_ultrafast import firefox

    monkeypatch.setenv("JEV_HTTP_TIMEOUT", "10")
    results = firefox.check_providers()
    assert results["policy"]["ok"] is True, results["policy"]["detail"]
    assert results["policy"]["latency_ms"] >= DELAY * 1000
