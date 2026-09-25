"""The live probe: it retries an endpoint that never answered, and never softens a verdict.

The 2026-09-25 run of `.github/workflows/real-provider-test.yml` went red because NVIDIA NIM
left `openai/gpt-oss-20b` unanswered for 76 s while the same provider answered for
`z-ai/glm-5.3` in the same run. The retry added here is for exactly that: no verdict at all.
A verdict — parameters verified, parameters refused — is reported as it came, first time, and
the parameter check stays a hard one.
"""

import importlib.util
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location(
    "real_provider_test", ROOT / "scripts" / "real_provider_test.py"
)
live = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(live)

STALL = {
    "probed": ["temperature", "seed"],
    "verified": [],
    "unsupported": [],
    "error": "Model connection failed; no action executed.",
}
VERDICT = {
    "probed": ["temperature", "seed"],
    "verified": ["temperature"],
    "unsupported": ["seed"],
    "error": None,
}


@pytest.fixture
def asleep(monkeypatch):
    """The retry pauses are real; the test does not wait them out."""
    monkeypatch.setattr(live.time, "sleep", lambda _seconds: None)


def probes(monkeypatch, reports):
    """Answer each probe call with the next canned report and record the calls."""
    calls = []

    def fake(name, model_id):
        calls.append((name, model_id))
        return reports.pop(0)

    monkeypatch.setattr(live.discovery, "probe_model", fake)
    return calls


def test_a_stalled_endpoint_is_asked_again_before_it_is_called_a_failure(asleep, monkeypatch):
    calls = probes(monkeypatch, [dict(STALL), dict(STALL), dict(VERDICT)])
    report, attempts, waited_ms = live.probe_with_retries("nvidia", "openai/gpt-oss-20b")
    assert attempts == 3, "the probe gave up before the endpoint had its chances"
    assert len(calls) == 3 and calls[0] == ("nvidia", "openai/gpt-oss-20b")
    assert report["verified"] == ["temperature"], "the retry lost the verdict it finally got"
    assert waited_ms >= 0


def test_a_stall_that_never_ends_is_still_a_failure(asleep, monkeypatch):
    calls = probes(monkeypatch, [dict(STALL) for _ in range(3)] + [dict(VERDICT)])
    report, attempts, _ = live.probe_with_retries("nvidia", "openai/gpt-oss-20b")
    assert attempts == 3 and len(calls) == 3, "a fourth attempt is not part of the contract"
    assert report["error"].startswith("Model connection failed"), "the endpoint's own failure vanished"


def test_a_real_verdict_is_never_retried(asleep, monkeypatch):
    calls = probes(monkeypatch, [dict(VERDICT), dict(STALL)])
    report, attempts, _ = live.probe_with_retries("groq", "openai/gpt-oss-20b")
    assert attempts == 1 and len(calls) == 1, "a verdict was asked for twice"
    assert report["unsupported"] == ["seed"], "a refusal must come back as a refusal"


def test_a_probe_that_raises_is_reported_not_retried(asleep, monkeypatch):
    calls = []

    def explode(name, model_id):
        calls.append((name, model_id))
        raise RuntimeError("No API key for nvidia (set NVIDIA_API_KEY).")

    monkeypatch.setattr(live.discovery, "probe_model", explode)
    report, attempts, _ = live.probe_with_retries("nvidia", "z-ai/glm-5.3")
    assert report is None and attempts == 1 and len(calls) == 1
    assert live.RESULTS[-1][0] == "🟡", "a missing key is a warning, not a retry loop"
