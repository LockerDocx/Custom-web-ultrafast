"""Contracts for the live flights E2E: pacing, the seven checks, and honest verdicts."""

import json
import time

import pytest

from examples.flights import FIELD_DATE, ISO_DATE, OPTION_DATE, verify
from jev_ultrafast import model, providers
from scripts import e2e_flights


def good_page():
    return {
        "url": "https://www.google.com/travel/flights/search?tfs=CBwQAhooEgoyMDI2LTA5LTIw&hl=en",
        "text": f"departing {ISO_DATE}",
        "actions": [
            {"label": "Change ticket type. One way", "value": "One way", "kind": "click"},
            {"label": "Where from?", "value": "Zürich", "kind": "fill"},
            {"label": "Where to?", "value": "London", "kind": "fill"},
            {"label": "Departure", "value": FIELD_DATE, "kind": "fill"},
            {"label": f"Select flight. {OPTION_DATE} · 07:00 - 08:05, 1 stop, from 120 EUR",
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
    def exploding(*args, **kwargs):
        raise RuntimeError("chrome not found")

    monkeypatch.setattr(e2e_flights, "warm_up", exploding)
    monkeypatch.setattr("jev_ultrafast.Agent", exploding)
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


def test_the_token_budget_holds_the_minute_and_waits_instead_of_overrunning():
    now = [0.0]
    slept = []

    def fake_sleep(seconds):
        now[0] += seconds
        slept.append(seconds)

    budget = e2e_flights.TokenWindow(tpm=100, window=60.0, clock=lambda: now[0], sleeper=fake_sleep)
    peaks = []
    for _ in range(4):
        budget.reserve(40)
        peaks.append(budget.used())
    assert max(peaks) <= 100, "a burst must never exceed the minute's allowance"
    assert slept and slept[0] >= 59, "the fourth call waits for the window to slide"
    reservation = budget.reserve(30)
    budget.settle(reservation, 5)
    assert budget.used() == 5, "the reservation is corrected to the provider's real usage"


def test_throttled_calls_are_retried_on_the_providers_own_schedule(monkeypatch):
    attempts = []

    def throttled(url, key, body, headers=None):
        attempts.append(1)
        if len(attempts) < 3:
            raise RuntimeError("Model provider returned HTTP 429: Rate limit reached; "
                               "Please try again in 4.5s; no action executed.")
        return {"choices": [{"message": {"content": "{}"}}], "usage": {"total_tokens": 12}}

    monkeypatch.setattr(model, "post_json", throttled)
    with e2e_flights.paced_requests(0.0, tpm=8000, retries=3, sleeper=lambda seconds: None) as paced:
        model.post_json("http://example.test", "k", {"max_tokens": 8})
    assert len(attempts) == 3
    assert paced["calls"] == 1 and paced["retries"] == 2
    assert paced["throttled_s"] == pytest.approx(10.0), "4.5 s of hint plus the safety margin, twice"


def test_a_real_provider_error_is_not_retried(monkeypatch):
    def broken(url, key, body, headers=None):
        raise RuntimeError("Model provider returned HTTP 400: bad request; no action executed.")

    monkeypatch.setattr(model, "post_json", broken)
    with e2e_flights.paced_requests(0.0, retries=3, sleeper=lambda seconds: None) as paced:
        with pytest.raises(RuntimeError):
            model.post_json("http://example.test", "k", {})
    assert paced["attempts"] == 1, "only throttling is worth retrying"


def test_the_report_names_the_rate_limiting_it_had_to_do():
    page = good_page()
    verification = verify(page)
    report = e2e_flights.render_report(
        "passed", "every page-state check holds",
        {"status": "done", "history": [1], "final_page": page, "verification": verification,
         "attempt": 2, "warm_up": {"ready_s": 1.5, "consent": True}},
        90.0, 2.4, {"calls": 12, "slept_s": 26.4, "retries": 3, "throttled_s": 15.5,
                    "tpm": 6000.0, "window_s": 60.0, "tokens": 5400.0},
        "/usr/bin/google-chrome")
    assert "Rate limiting" in report
    assert "**3** throttled retries" in report
    assert "token budget 6,000/min" in report
    assert "cookie wall dismissed" in report
    assert "Attempts: **2**" in report


def fake_browser_class():
    class FakeBrowser:
        def __init__(self, url):
            self.url = url
            self.clicks = []
            self.pages = [
                {"url": url, "text": "", "actions": []},
                {"url": url, "text": "Before you continue to Google", "actions": [
                    {"id": "a1", "label": "Accept all", "kind": "click"}]},
                {"url": url, "text": "Flights", "actions": [
                    {"id": "b1", "label": "One way", "kind": "click"}]},
            ]

        def observe(self, screenshot=True):
            return self.pages.pop(0) if len(self.pages) > 1 else self.pages[0]

        def act(self, action, page, text=None):
            self.clicks.append(action["label"])

    return FakeBrowser


def test_warm_up_waits_for_the_form_and_clears_the_cookie_wall():
    browser, page, notes = e2e_flights.warm_up(seconds=5.0, poll=0.0, sleeper=lambda seconds: None,
                                               factory=fake_browser_class())
    assert browser.clicks == ["Accept all"], "a fresh profile meets the wall before the form"
    assert notes["consent"] is True
    assert e2e_flights._interactive(page), "the warm-up returns only once the form is on screen"


def test_a_run_that_died_before_its_first_action_is_retried():
    blocked = {"history": [], "status": "blocked"}
    assert e2e_flights._worth_retrying(blocked, None, False) is True
    assert e2e_flights._worth_retrying({"history": [1], "status": "blocked"}, None, False) is False
    assert e2e_flights._worth_retrying(blocked, "RuntimeError: boom", False) is False
    assert e2e_flights._worth_retrying({"history": [], "status": "done"}, None, False) is False
    assert e2e_flights._worth_retrying(blocked, None, True) is False


def test_run_mission_retries_a_page_that_was_not_ready(monkeypatch):
    calls = []

    def fake_attempt(agent_class, max_seconds, started, warm_up_seconds=25.0):
        calls.append(1)
        if len(calls) == 1:
            return ({"history": [], "status": "blocked", "final_page": {"url": "", "text": "", "actions": []},
                     "verification": {"passed": False, "checks": {}}}, None, False,
                    {"ready_s": 0.4, "consent": False})
        page = good_page()
        return ({"history": [1], "status": "done", "final_page": page, "verification": verify(page)},
                None, False, {"ready_s": 1.2, "consent": True})

    monkeypatch.setattr(e2e_flights, "_attempt", fake_attempt)
    monkeypatch.setattr(e2e_flights.time, "sleep", lambda seconds: None)
    state, error, timed_out, _seconds = e2e_flights.run_mission(60, "")
    assert len(calls) == 2, "the run that never touched the page is retried once"
    assert state["attempt"] == 2
    assert state["verification"]["passed"] is True
    assert state["warm_up"]["consent"] is True
    assert error is None and timed_out is False


def test_each_provider_gets_its_own_token_budget(monkeypatch):
    slept = []

    def fake_post_json(url, key, body, headers=None):
        return {"choices": [{"message": {"content": "{}"}}], "usage": {"total_tokens": 30}}

    monkeypatch.setattr(model, "post_json", fake_post_json)
    with e2e_flights.paced_requests(0.0, tpm=100, retries=0, sleeper=slept.append) as paced:
        for _ in range(3):
            model.post_json("https://api.groq.com/openai/v1/chat/completions", "k", {"max_tokens": 4})
        # A different provider must not inherit the first one's spent allowance.
        model.post_json("https://integrate.api.nvidia.com/v1/chat/completions", "k", {"max_tokens": 4})
    assert paced["budgets"] == {"api.groq.com": 90.0, "integrate.api.nvidia.com": 30.0}
    assert not slept, "three 30-token calls fit in a 100-token minute"


def test_the_report_shows_what_the_agent_did_and_what_it_could_see():
    page = good_page()
    verification = verify(page)
    state = {
        "status": "blocked", "history": [1], "final_page": page, "verification": verification,
        "steps": [{"elapsed_ms": 10, "status": "ready", "action": "Where from?", "kind": "fill",
                   "operation": "fill", "target": "Where from?", "page_changed": False}],
    }
    report = e2e_flights.render_report("failed", "checks not satisfied: results", state, 12.0, 2.4,
                                       {"calls": 3, "slept_s": 4.8}, "chrome")
    assert "What the agent did (1 step(s))" in report
    assert "| 1 | Where from?" in report
    assert "Controls the agent could see at the end" in report
    assert "Select flight." in report, "the visible controls are the diagnosis a failed run needs"


def test_the_report_names_the_models_that_ran():
    page = good_page()
    verification = verify(page)
    state = {
        "status": "blocked", "history": [], "final_page": page, "verification": verification,
        "planner": "z-ai/glm-5.3",
        "decisions": [{"model": "z-ai/glm-5.3", "request": {"provider": "nvidia", "model": "z-ai/glm-5.3"}}],
        "text_calls": [{"model": "openai/gpt-oss-20b"}],
    }
    report = e2e_flights.render_report("failed", "checks not satisfied: results", state, 20.0, 1.5,
                                       {"calls": 2, "slept_s": 1.5}, "chrome")
    assert "planner `z-ai/glm-5.3`" in report
    assert "policy `nvidia:z-ai/glm-5.3`" in report
    assert "text `openai/gpt-oss-20b`" in report
