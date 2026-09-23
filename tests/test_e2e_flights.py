"""Contracts for the live flights E2E: pacing, the seven checks, and honest verdicts."""

import json
import time

import pytest

from examples.flights import verify
from jev_ultrafast import model, providers
from scripts import e2e_flights


def good_page():
    return {
        "url": "https://www.google.com/travel/flights/search?tfs=CBwQAhooEgoyMDI2LTA5LTIw&hl=en",
        "text": "departing 2026-09-20",
        "actions": [
            {"label": "Change ticket type. One way", "value": "One way", "kind": "click"},
            {"label": "Where from?", "value": "Zürich", "kind": "fill"},
            {"label": "Where to?", "value": "London", "kind": "fill"},
            {"label": "Departure", "value": "Sun, Sep 20", "kind": "fill"},
            {"label": "Select flight. Sunday, September 20 · 07:00 - 08:05, 1 stop, from 120 EUR",
             "value": "", "kind": "click"},
        ],
    }


def test_the_missions_own_verification_has_seven_checks():
    result = verify(good_page())
    assert result["passed"] is True
    assert len(result["checks"]) == 7
    assert result["visible_flights"], "the results check needs real Select-flight entries"


def test_pacing_spaces_every_model_call_and_restores_the_seam(monkeypatch):
    stamps = []

    def fake_post_json(url, key, body, headers=None):
        stamps.append(time.perf_counter())
        return {"choices": [{"message": {"content": "{}"}}]}

    monkeypatch.setattr(model, "post_json", fake_post_json)
    with e2e_flights.paced_requests(0.05) as paced:
        for _ in range(3):
            model.post_json("http://example.test", "k", {})
    gaps = [b - a for a, b in zip(stamps, stamps[1:])]
    assert paced["calls"] == 3
    assert paced["slept_s"] == pytest.approx(0.10)
    assert all(gap >= 0.045 for gap in gaps), gaps
    assert model.post_json is fake_post_json, "the wrapper must restore what it replaced"


def test_pacing_also_wraps_streaming(monkeypatch):
    def fake_stream(url, key, body, headers=None, on_delta=None):
        return ("{}", {"prompt_tokens": 1}, "fake")

    monkeypatch.setattr(model, "post_stream", fake_stream)
    with e2e_flights.paced_requests(0.01) as paced:
        model.post_stream("http://example.test", "k", {})
    assert paced["calls"] == 1


def test_classify_reports_the_four_real_situations():
    page = good_page()
    verified = verify(page)
    assert e2e_flights.classify(page, verified)[0] == "passed"
    assert e2e_flights.classify(page, {"passed": False, "checks": {"results": False}})[0] == "failed"
    assert e2e_flights.classify(page, verified, timed_out=True)[0] == "failed"
    assert e2e_flights.classify(page, verified, error="RuntimeError: boom")[0] == "failed"
    consent = {"url": "https://consent.google.com/ml?continue=x", "text": "Before you continue to Google",
               "actions": []}
    outcome, reason = e2e_flights.classify(consent, verify(consent))
    assert outcome == "site_blocked"
    assert "consent" in reason or "google.com" in reason


def test_classify_names_the_checks_that_failed():
    page = good_page()
    broken = {**page, "actions": [a for a in page["actions"] if "Select flight" not in a["label"]]}
    outcome, reason = e2e_flights.classify(broken, verify(broken))
    assert outcome == "failed"
    assert "results" in reason


def test_report_shows_the_checks_calls_and_url():
    page = good_page()
    verification = verify(page)
    state = {"status": "done", "history": [1, 2, 3], "final_page": page, "verification": verification}
    report = e2e_flights.render_report("passed", "every page-state check holds", state, 42.0, 2.4,
                                       {"calls": 7, "slept_s": 14.4}, "/usr/bin/google-chrome")
    assert "✅ **passed**" in report
    assert "42.0 s" in report and "**7**" in report and "2.4 s pacing" in report
    assert "| results | ✅ |" in report
    assert page["url"] in report


def test_report_marks_a_site_block_as_a_warning_not_a_pass():
    page = {"url": "https://consent.google.com/", "text": "Before you continue", "actions": []}
    verification = verify(page)
    outcome, reason = e2e_flights.classify(page, verification)
    report = e2e_flights.render_report(outcome, reason, {"verification": verification}, 3.0, 2.4,
                                       {"calls": 0, "slept_s": 0.0}, "chrome")
    assert "⚠️" in report and "✅ **passed**" not in report


def test_preflight_lists_every_missing_precondition(monkeypatch):
    def unavailable(role):
        raise ValueError(f"{role.upper()}_MODEL is not set")

    monkeypatch.setattr(providers, "resolve", unavailable)
    monkeypatch.delenv("CHROME_PATH", raising=False)
    monkeypatch.delenv("BH_CHROME_PATH", raising=False)
    monkeypatch.setattr(e2e_flights.shutil, "which", lambda name: None)
    chrome, reasons = e2e_flights.preflight()
    assert chrome is None
    assert len(reasons) == 3
    assert any("POLICY" in reason for reason in reasons)
    assert any("Chrome" in reason for reason in reasons)


def test_preflight_accepts_a_configured_environment(monkeypatch):
    monkeypatch.setattr(providers, "resolve", lambda role: {"name": "fake", "model": "m"})
    monkeypatch.setenv("CHROME_PATH", "/usr/bin/google-chrome")
    chrome, reasons = e2e_flights.preflight()
    assert chrome == "/usr/bin/google-chrome"
    assert reasons == []


def test_selftest_passes_offline():
    assert e2e_flights.selftest(0.01) == 0


def test_main_skips_cleanly_without_preconditions(monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(e2e_flights, "preflight", lambda: (None, ["policy: POLICYY_MODEL is not set"]))
    destination = tmp_path / "e2e.json"
    monkeypatch.setattr(e2e_flights.sys, "argv", ["e2e_flights.py", "--json", str(destination)])
    assert e2e_flights.main() == 0
    payload = json.loads(destination.read_text(encoding="utf-8"))
    assert payload["outcome"] == "skipped"
    assert "Skipped" in capsys.readouterr().out


def test_run_mission_reports_a_browser_that_will_not_start(monkeypatch):
    class ExplodingAgent:
        def __init__(self, *args, **kwargs):
            raise RuntimeError("chrome not found")

    monkeypatch.setattr("jev_ultrafast.Agent", ExplodingAgent)
    state, error, timed_out, _seconds = e2e_flights.run_mission(5, "")
    assert state is None
    assert "chrome not found" in error
    assert timed_out is False


def test_main_fails_when_the_mission_ran_but_the_page_is_wrong(monkeypatch, tmp_path, capsys):
    page = {"url": "https://www.google.com/travel/flights?hl=en", "text": "Flights", "actions": []}
    state = {"status": "blocked", "history": [], "final_page": page, "verification": verify(page)}
    monkeypatch.setattr(e2e_flights, "preflight", lambda: ("/usr/bin/google-chrome", []))
    monkeypatch.setattr(e2e_flights, "run_mission", lambda max_seconds, artifacts: (state, None, False, 12.0))
    monkeypatch.setattr(e2e_flights.sys, "argv", ["e2e_flights.py", "--json", str(tmp_path / "e2e.json")])
    assert e2e_flights.main() == 1
    assert "🔴 **failed**" in capsys.readouterr().out
