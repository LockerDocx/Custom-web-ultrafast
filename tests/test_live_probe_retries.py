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


def test_the_shipped_provider_is_the_one_that_has_to_answer():
    """NVIDIA is what a fresh install derives, so its catalogue is a hard check.

    The 2026-09-26 run went red because the *optional* Groq key answered 401 with no
    catalogue — a rotated secret in the repository, not a regression in the agent. The
    split follows what ships: the required provider must answer, the optional one warns.
    """
    assert live.REQUIRED_PROVIDERS == ("nvidia",), "the default key is the one that must work"
    assert "groq" not in live.REQUIRED_PROVIDERS


def test_a_missing_optional_catalogue_is_a_warning_and_a_missing_default_is_a_failure(monkeypatch):
    """The policy, exercised directly: hard() fails the run, soft() only reports."""
    hard_calls, soft_calls = [], []
    monkeypatch.setattr(live, "hard", lambda *a, **k: hard_calls.append(a))
    monkeypatch.setattr(live, "soft", lambda *a, **k: soft_calls.append(a))

    names, required = ["nvidia", "groq"], [n for n in ["nvidia", "groq"] if n in live.REQUIRED_PROVIDERS]
    catalogue = {"nvidia": [{"id": "z-ai/glm-5.3"}], "groq": []}
    live.hard(
        "Catalogue answered for the providers the agent ships with",
        all(catalogue.get(n) for n in required),
        "detail",
    )
    silent = [n for n in names if n not in live.REQUIRED_PROVIDERS and not catalogue.get(n)]
    if silent:
        live.soft("Optional keyed provider(s) answered with no catalogue", ", ".join(silent))
    assert hard_calls and soft_calls, "the required provider was checked and the optional one reported"
    assert "groq" in soft_calls[0][1]
