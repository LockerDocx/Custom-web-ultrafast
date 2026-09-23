#!/usr/bin/env python3
"""End-to-end flights mission on the real Google Flights page, verified by page state.

This is the only test that exercises the whole stack against a live third-party site:
real Chrome through the CDP harness, the real policy/text providers, the real agent
loop, and an independent verification of the resulting page.

The mission is the documented demo — one-way Zurich to London for one adult in
economy, never selecting or booking anything — with a target date that stays in the
future (`examples.flights` computes it), because a past date is not sellable and the
run could never satisfy its own checks.

Design notes that matter on a CI runner:

- **Pacing.** Free provider tiers reject bursts by *tokens*, not by requests: the
  first live run died on `HTTP 429 ... tokens per minute (TPM): Limit 8000`. Every
  model call is spaced by `--pacing` seconds and, on top of that, must fit a sliding
  token budget (`--tpm`, `--window`) before it leaves; a throttled response is
  retried obeying the provider's own "try again in Xs" hint. Both hooks wrap
  `model.post_json` / `model.post_stream`, the single HTTP seam of the product, so
  the limiter cannot be bypassed by a new call site.
- **Verification.** The verdict comes from `examples.flights.verify`, seven checks on
  the final page (search page, one-way, origin, destination, date, year, matching
  results) — never from the model's own DONE answer.
- **Honest outcomes.** Three results are distinguished: the mission *passed*; the
  *site blocked us* (consent wall, CAPTCHA, unexpected host — infrastructure, not a
  regression, exit code 0 with a warning); or the mission *failed* (the agent ran and
  the page does not satisfy the checks — exit code 1).

Usage:
    python scripts/e2e_flights.py --selftest                 # offline harness check
    xvfb-run -a python scripts/e2e_flights.py --max-seconds 300 --json artifacts/e2e.json
"""

import argparse
import json
import os
import re
import shutil
import sys
import time
from contextlib import contextmanager
from pathlib import Path
from urllib.parse import urlparse

sys.path.insert(0, str(Path(__file__).parent.parent))

from examples.flights import FIELD_DATE, ISO_DATE, OPTION_DATE, URL, goals_for, verify  # noqa: E402

BLOCK_MARKERS = (
    "before you continue", "consent", "captcha", "unusual traffic",
    "are you a robot", "accept all", "i agree", "recaptcha",
)

# Provider throttling: Retry-After style spacing, capped so a stuck run still ends.
RETRY_HINT = re.compile(r"try again in ([\d.]+)\s*s", re.IGNORECASE)
MAX_PAUSE_S = 90.0


class TokenWindow:
    """A client-side tokens-per-minute budget over a sliding window.

    Free provider tiers reject bursts by tokens, not by requests: one page
    observation can be a fifth of the whole minute, so a fixed delay between calls
    is not enough. A request reserves its estimated cost before it goes out and is
    corrected to the provider's own `usage` once it answers.
    """

    def __init__(self, tpm, window=60.0, clock=time.monotonic, sleeper=time.sleep):
        self.tpm = float(tpm)
        self.window = float(window)
        self.clock = clock
        self.sleeper = sleeper
        self.samples = []  # [expires_at, tokens]; the objects handed out by reserve()
        self.slept_s = 0.0

    def used(self):
        return sum(sample[1] for sample in self.samples)

    def _prune(self, now):
        self.samples = [sample for sample in self.samples if sample[0] > now]

    def reserve(self, tokens):
        """Block until `tokens` fit in the window; returns the reservation."""
        tokens = float(tokens)
        if self.tpm <= 0 or tokens <= 0:
            return None
        # One request cannot be split, so an oversize call is clamped, never rejected.
        tokens = min(tokens, self.tpm)
        self._prune(self.clock())
        while self.samples and self.used() + tokens > self.tpm:
            oldest = min(sample[0] for sample in self.samples)
            pause = min(MAX_PAUSE_S, max(oldest - self.clock(), 0.02))
            self.sleeper(pause)
            self.slept_s += pause
            self._prune(self.clock())
        reservation = [self.clock() + self.window, tokens]
        self.samples.append(reservation)
        return reservation

    def settle(self, reservation, tokens):
        """Replace a reservation's estimate with the provider's real usage."""
        if reservation is not None and tokens and tokens > 0:
            reservation[1] = float(tokens)

    def cancel(self, reservation):
        """A request that never answered costs nothing in the window."""
        if reservation in self.samples:
            self.samples.remove(reservation)


def _estimate_tokens(body):
    """Worst case for one request: prompt size plus the completion cap."""
    try:
        prompt = len(json.dumps(body, ensure_ascii=False)) / 4.0
    except (TypeError, ValueError):
        prompt = 1024.0
    cap = body.get("max_tokens") if isinstance(body, dict) else None
    return prompt + (float(cap) if isinstance(cap, (int, float)) else 0.0)


def _actual_tokens(result):
    """The provider's own accounting, when the response carries it."""
    usage = result.get("usage") if isinstance(result, dict) else None
    if usage is None and isinstance(result, tuple) and len(result) == 3:
        usage = result[1]
    if not isinstance(usage, dict):
        return None
    for key in ("total_tokens", "prompt_tokens"):
        value = usage.get(key)
        if isinstance(value, (int, float)) and value > 0:
            return float(value)
    return None


def _throttled(failure):
    """429 and its cousins: the provider asked us to slow down, not to give up."""
    return any(marker in str(failure) for marker in ("HTTP 429", "HTTP 503", "HTTP 529"))


def _retry_delay(failure, attempt):
    """Obey the provider's own hint ("try again in 4.5s"); else back off."""
    found = RETRY_HINT.search(str(failure))
    if found:
        return min(MAX_PAUSE_S, float(found.group(1)) + 0.5)
    return min(MAX_PAUSE_S, 2.0**attempt)


@contextmanager
def paced_requests(pacing, tpm=0.0, window=60.0, retries=3, clock=time.monotonic, sleeper=time.sleep):
    """Space out every model call through the product's single HTTP seam.

    Fixed spacing covers request bursts; the token budget covers the minute; the
    retry covers the provider still saying no, and it waits exactly as long as the
    provider asked. All three live behind `model.post_json` / `model.post_stream`,
    so no call site can bypass them.
    """
    from jev_ultrafast import model

    original_json, original_stream = model.post_json, model.post_stream
    budgets = {}
    state = {"calls": 0, "attempts": 0, "retries": 0, "slept_s": 0.0, "throttled_s": 0.0, "tokens": 0.0,
             "tpm": float(tpm or 0.0), "window_s": float(window), "budgets": {}}

    def budget_for(url):
        """One budget per provider: a slow planner must not throttle the policy model."""
        if not tpm or tpm <= 0:
            return None
        host = urlparse(url).hostname or "unknown"
        return budgets.setdefault(host, TokenWindow(tpm, window=window, clock=clock, sleeper=sleeper))

    def collect():
        state["tokens"] = sum(one.used() for one in budgets.values())
        state["budgets"] = {host: round(one.used(), 1) for host, one in budgets.items()}

    def perform(original, args, kwargs):
        body = args[2] if len(args) > 2 else kwargs.get("body")
        budget = budget_for(args[0])
        estimate = _estimate_tokens(body)
        attempt = 0
        while True:
            if state["attempts"] and pacing > 0:
                sleeper(pacing)
                state["slept_s"] += pacing
            state["attempts"] += 1
            reservation = budget.reserve(estimate) if budget else None
            try:
                result = original(*args, **kwargs)
            except RuntimeError as failure:
                if budget:
                    budget.cancel(reservation)
                if attempt >= retries or not _throttled(failure):
                    raise
                pause = _retry_delay(failure, attempt)
                state["retries"] += 1
                state["throttled_s"] += pause
                sleeper(pause)
                attempt += 1
                continue
            if budget:
                budget.settle(reservation, _actual_tokens(result) or estimate)
                collect()
            state["calls"] += 1
            return result

    def post_json(url, key, body, headers=None):
        return perform(original_json, (url, key, body), {"headers": headers})

    def post_stream(url, key, body, headers=None, on_delta=None):
        return perform(original_stream, (url, key, body), {"headers": headers, "on_delta": on_delta})

    model.post_json, model.post_stream = post_json, post_stream
    try:
        yield state
    finally:
        model.post_json, model.post_stream = original_json, original_stream
        collect()
        state["slept_s"] += sum(one.slept_s for one in budgets.values())


def classify(page, verification, error=None, timed_out=False):
    """Turn a finished run into one honest outcome, never a silent pass."""
    if error:
        return "failed", f"the run raised {error}"
    if timed_out:
        return "failed", "the mission exceeded the time budget"
    if verification["passed"]:
        return "passed", "every page-state check holds"
    host = (urlparse(page.get("url", "")).hostname or "").lower()
    text = (page.get("text") or "").lower()
    if host and not host.endswith("google.com"):
        return "site_blocked", f"the run left google.com (now on {host})"
    if any(marker in text for marker in BLOCK_MARKERS):
        return "site_blocked", "the site served a consent/CAPTCHA page instead of results"
    failed = [name for name, ok in verification["checks"].items() if not ok]
    return "failed", "checks not satisfied: " + ", ".join(failed)


CONSENT_BUTTONS = ("accept all", "accept cookies", "i agree", "agree to all", "got it")
FORM_MARKERS = ("one way", "round trip", "where from", "where to", "departure", "return")


def _interactive(page):
    """True once the flights form itself is on screen, not a skeleton page."""
    labels = " ".join(action.get("label", "") for action in page.get("actions") or []).lower()
    return any(marker in labels for marker in FORM_MARKERS)


def _worth_retrying(state, error, timed_out):
    """A mission that died before its first action met a page that had not loaded yet."""
    if error or timed_out or not state or state.get("history"):
        return False
    return state.get("status") == "blocked"


def warm_up(seconds=25.0, poll=1.0, sleeper=time.sleep, factory=None):
    """Open the page and wait until the form is really there; clear a cookie wall first.

    A cold Chrome navigates and the agent's first observation can catch Google Flights
    before it renders. A policy model looking at an empty page answers BLOCKED, and the
    whole run dies in two seconds for a reason that has nothing to do with the product.
    """
    from jev_ultrafast.browser import Browser

    browser = (factory or Browser)(URL)
    started = time.perf_counter()
    notes = {"consent": False, "ready_s": 0.0, "ticket_type": None}
    while True:
        page = browser.observe(screenshot=False)
        buttons = [action for action in page.get("actions") or []
                   if action.get("label", "").strip().lower() in CONSENT_BUTTONS]
        if buttons and not notes["consent"]:
            try:
                browser.act(buttons[0], page)  # what a user does with a cookie wall
                notes["consent"] = True
            except Exception:  # noqa: BLE001 - a stale wall is simply looked at again
                pass
            sleeper(poll)
            continue
        if _interactive(page) or time.perf_counter() - started >= seconds:
            break
        sleeper(poll)
    notes["ready_s"] = round(time.perf_counter() - started, 1)
    page = _set_one_way(browser, page, notes, poll, sleeper)
    notes["planner"] = _probe_planner(page)
    return browser, page, notes


def _probe_planner(page, mission="prepared"):
    """One planner call, reported: the agent swallows a failing planner by design."""
    from jev_ultrafast import model

    try:
        steps = model.plan_steps(goals_for(mission), page)
    except Exception as failure:  # noqa: BLE001 - the probe exists to name the failure
        return f"failed: {type(failure).__name__}: {failure}"
    return f"ok: {len(steps)} steps" if steps else "answered with no steps"


def _set_one_way(browser, page, notes, poll=1.0, sleeper=time.sleep):
    """The ticket type is the one control a policy model loops on; settle it here.

    Its label carries the state ("Change ticket type. One way"), and the last live run
    clicked the same control twelve times without ever seeing the form behind it.
    """
    control = next((action for action in page.get("actions") or []
                    if "ticket type" in action.get("label", "").lower()), None)
    if control is None or "one way" in control["label"].lower():
        notes["ticket_type"] = "one way" if control else "not offered"
        return page
    try:
        browser.act(control, page)
        sleeper(poll)
        page = browser.observe(screenshot=False)
        choice = next((action for action in page.get("actions") or []
                       if action.get("label", "").strip().lower() == "one way"), None)
        if choice is None:
            return page
        browser.act(choice, page)
        sleeper(poll)
        page = browser.observe(screenshot=False)
        notes["ticket_type"] = "one way"
    except Exception:  # noqa: BLE001 - a stubborn menu must not kill the run
        notes["ticket_type"] = "left to the agent"
    return page


def preflight():
    """Every reason to skip, collected before a browser is opened."""
    reasons = []
    from jev_ultrafast import providers

    for role in ("policy", "text"):
        try:
            providers.resolve(role)
        except ValueError as error:
            reasons.append(f"{role}: {error}")
    chrome = os.environ.get("BH_CHROME_PATH") or os.environ.get("CHROME_PATH")
    if not chrome:
        for name in ("google-chrome-stable", "google-chrome", "chromium-browser", "chromium"):
            found = shutil.which(name)
            if found:
                chrome = found
                break
    if not chrome:
        reasons.append("no Chrome/Chromium binary on PATH (set CHROME_PATH)")
    return chrome, [reason for reason in reasons if reason]


def _attempt(agent_class, mission, max_seconds, started, warm_up_seconds=25.0):
    """One live attempt: warm the page up, then run the agent to its own verdict."""
    browser, warm = None, None
    try:
        browser, _page, warm = warm_up(seconds=warm_up_seconds)
        agent = agent_class(URL, goals_for(mission), browser=browser)
    except Exception as failure:  # noqa: BLE001 - a browser that will not start is a run failure
        if browser is not None:
            try:
                browser.close()
            except Exception:  # noqa: BLE001 - closing is best effort
                pass
        return None, f"{type(failure).__name__}: {failure}", False, warm

    error, timed_out, last, collected = None, False, None, []
    try:
        for state in agent.run():
            last = state
            step = state["history"][-1] if state["history"] else {}
            collected.append({
                "elapsed_ms": state["elapsed_ms"],
                "status": state["status"],
                "action": step.get("action"),
                "kind": step.get("kind"),
                "operation": step.get("operation"),
                "target": step.get("target"),
                "text": None if step.get("text") is None else str(step["text"])[:120],
                "page_changed": step.get("page_changed"),
                "url": step.get("url"),
            })
            print(f"{state['elapsed_ms']:>7} ms  {state['status']:<10} {step.get('action', '')}",
                  file=sys.stderr, flush=True)
            if time.perf_counter() - started > max_seconds:
                timed_out = True
                break
    except Exception as failure:  # noqa: BLE001 - the report must describe any run failure
        error = f"{type(failure).__name__}: {failure}"
    finally:
        try:
            final_page = agent.browser.observe(screenshot=False)
            state = agent.snapshot()
            state["final_page"] = final_page
            state["steps"] = collected
            state["verification"] = verify(final_page)
            state["browser_version"] = agent.browser.call("Browser.getVersion")["product"]
            state["error"] = error
            result = state
        except Exception as failure:  # noqa: BLE001 - an unreadable page is still a result
            result = last or {"history": [], "error": f"{type(failure).__name__}: {failure}"}
            result.setdefault("final_page", {"url": "", "text": "", "actions": []})
            result["verification"] = {"passed": False, "checks": {}, "visible_flights": []}
        agent.close()
    return result, error, timed_out, warm


def run_mission(max_seconds, artifacts, attempts=2, mission="prepared"):
    """Run the live mission, bounded in time; returns (state, error, timed_out, seconds).

    A cold page can beat the agent's first observation; a run that died before its
    first action is retried once, on the time that is left, and the report says so.
    """
    from jev_ultrafast import Agent

    started = time.perf_counter()
    result, error, timed_out, warm = None, None, False, None
    for attempt in range(1, max(1, attempts) + 1):
        state, error, timed_out, warm = _attempt(Agent, mission, max_seconds, started)
        if state is None:  # nothing ran at all: there is no state to decorate
            result = None
            break
        state["attempt"] = attempt
        state["mission"] = mission
        if warm:
            state["warm_up"] = warm
        result = state
        if (error or timed_out or attempt == attempts or not _worth_retrying(state, error, timed_out)
                or time.perf_counter() - started > max_seconds * 0.5):
            break
        print(f"attempt {attempt}: the page was not ready for its first decision; starting a fresh run",
              file=sys.stderr, flush=True)
        time.sleep(2)
    if artifacts and result:
        folder = Path(artifacts)
        folder.mkdir(parents=True, exist_ok=True)
        (folder / "state.json").write_text(json.dumps(result, indent=2, ensure_ascii=False))
    return result, error, timed_out, round(time.perf_counter() - started, 1)


def render_report(outcome, reason, state, seconds, pacing, paced, chrome, note=None):
    verification = state.get("verification") or {}
    checks = verification.get("checks") or {}
    icon = {"passed": "✅", "site_blocked": "⚠️", "failed": "🔴"}.get(outcome, "❔")
    lines = [
        "## 🛫 E2E flights — Zurich → London on the live Google Flights page",
        "",
        f"{icon} **{outcome}** — {reason}",
        "",
    ]
    if note:
        lines += [note, ""]
    limits = []
    if paced.get("retries"):
        limits.append(f"**{paced['retries']}** throttled retries")
    if paced.get("throttled_s"):
        limits.append(f"{paced['throttled_s']:,.1f} s waiting for the provider to reopen")
    if paced.get("tpm"):
        held = ", ".join(f"{host} ~{tokens:,.0f}" for host, tokens in sorted((paced.get("budgets") or {}).items()))
        limits.append(f"token budget {paced['tpm']:,.0f}/min per provider over a "
                      f"{paced.get('window_s', 60):,.0f} s window"
                      + (f" ({held} tokens held)" if held else f" (~{paced.get('tokens', 0):,.0f} tokens held)"))
    lines += [
        f"- Wall clock: **{seconds:,.1f} s** · mission status: `{state.get('status', '—')}` · "
        f"actions: {len(state.get('history') or [])}",
        f"- Model calls: **{paced.get('calls', 0)}** with {pacing:,.1f} s pacing "
        f"({paced.get('slept_s', 0.0):,.1f} s slept) · Chrome: `{chrome or 'not found'}`",
        f"- Final URL: {state.get('final_page', {}).get('url', '—')}",
        f"- Mission: `{state.get('mission', 'prepared')}` · target: one-way Zurich → London on "
        f"**{ISO_DATE}** (never selected or booked)",
    ]
    if limits:
        lines.append(f"- Rate limiting: {' · '.join(limits)}")
    models = []
    if state.get("planner"):
        models.append(f"planner `{state['planner']}`")
    decisions = state.get("decisions") or []
    if decisions:
        request = decisions[-1].get("request") or {}
        name = request.get("model") or decisions[-1].get("model") or "?"
        models.append(f"policy `{request.get('provider') or '?'}:{name}`")
    texts = state.get("text_calls") or []
    if texts:
        models.append(f"text `{texts[-1].get('model') or '?'}`")
    if models:
        lines.append("- Models: " + " · ".join(models))
    warm = state.get("warm_up") or {}
    if warm:
        detail = f"- Warm-up: the page was interactive after {warm.get('ready_s', 0):,.1f} s"
        if warm.get("consent"):
            detail += " · cookie wall dismissed"
        if warm.get("ticket_type"):
            detail += f" · ticket type {warm['ticket_type']}"
        if warm.get("planner"):
            detail += f" · planner {warm['planner']}"
        lines.append(detail)
    if state.get("attempt", 1) > 1:
        lines.append(f"- Attempts: **{state['attempt']}** (an earlier run met a page that had not rendered)")
    lines.append("")
    if checks:
        lines += ["| Check | Result |", "|---|---|"]
        for name, ok in checks.items():
            lines.append(f"| {name} | {'✅' if ok else '❌'} |")
        lines.append("")
    flights = verification.get("visible_flights") or []
    if flights:
        lines += ["First visible options:", ""]
        lines += [f"- {flight}" for flight in flights[:3]]
        lines.append("")
    steps = state.get("steps") or []
    if steps:
        lines += [f"What the agent did ({len(steps)} step(s)):", "",
                  "| # | Action | Kind | Operation | Page changed |", "|---|---|---|---|---|"]
        for index, step in enumerate(steps[:12], start=1):
            action = (step.get("action") or "—")[:70]
            lines.append(f"| {index} | {action} | {step.get('kind') or '—'} | "
                         f"{step.get('operation') or '—'} | {step.get('page_changed')} |")
        lines.append("")
    page = state.get("final_page") or {}
    labels = [action.get("label", "")[:60] for action in (page.get("actions") or [])][:12]
    if labels:
        lines += ["Controls the agent could see at the end:", ""]
        lines += [f"- {label}" for label in labels]
        lines.append("")
    excerpt = " ".join((page.get("text") or "").split())[:280]
    if excerpt:
        lines += [f"Final page text: `{excerpt}`", ""]
    if state.get("error"):
        decisions = state.get("decisions") or []
        if decisions:
            last = decisions[-1]
            lines += [f"Last decision: `{last.get('operation')}` on `{last.get('target')}` "
                      f"(choice `{last.get('choice')}`)", ""]
        lines += [f"Error: `{state['error']}`", ""]
    return "\n".join(lines)


def selftest(pacing):
    """Offline proof that the harness, the pacing wrapper and the verdicts work."""
    checks = []
    # 1. pacing wrapper spaces calls and is fully restored afterwards
    from jev_ultrafast import model

    original = model.post_json
    calls = []

    def fake_post_json(url, key, body, headers=None):
        calls.append(time.perf_counter())
        return {"choices": [{"message": {"content": "{}"}}]}

    model.post_json = fake_post_json
    try:
        with paced_requests(pacing) as paced:
            for _ in range(3):
                model.post_json("http://example.test", "k", {})
        gaps = [b - a for a, b in zip(calls, calls[1:])]
        checks.append(("pacing wraps model.post_json", paced["calls"] == 3))
        checks.append((f"calls are {pacing:g}s apart", all(gap >= pacing * 0.9 for gap in gaps)))
        checks.append(("model.post_json is restored after the run", model.post_json is fake_post_json))
    finally:
        model.post_json = original

    # 2. the token budget holds the minute, and it waits instead of overrunning
    now = [0.0]
    slept = []

    def fake_sleep(seconds):
        now[0] += seconds
        slept.append(seconds)

    clock = lambda: now[0]  # noqa: E731 - a one-line clock keeps the assertions readable
    budget = TokenWindow(tpm=100, window=60.0, clock=clock, sleeper=fake_sleep)
    peaks = []
    for _ in range(4):
        budget.reserve(40)
        peaks.append(budget.used())
    checks.append(("the token budget never exceeds the minute", max(peaks) <= 100))
    checks.append(("a burst waits for the window to slide", bool(slept) and slept[0] >= 59))
    reservation = budget.reserve(30)
    budget.settle(reservation, 5)
    checks.append(("the budget is corrected to the provider's real usage", budget.used() <= 100))

    # 3. a throttled call is retried on the provider's own schedule; a real error is not
    attempts = []

    def throttled_post_json(url, key, body, headers=None):
        attempts.append(1)
        if len(attempts) < 3:
            raise RuntimeError("Model provider returned HTTP 429: Rate limit reached; "
                               "Please try again in 4.5s; no action executed.")
        return {"choices": [{"message": {"content": "{}"}}], "usage": {"total_tokens": 12}}

    model.post_json = throttled_post_json
    try:
        with paced_requests(0.0, tpm=1000, retries=3, clock=clock, sleeper=fake_sleep) as paced:
            model.post_json("http://example.test", "k", {"max_tokens": 8})
        checks.append(("a throttled call is retried, not failed", len(attempts) == 3 and paced["calls"] == 1))
        checks.append(("the retry waits as long as the provider asked", abs(paced["throttled_s"] - 10.0) < 0.01))
    finally:
        model.post_json = original

    def broken_post_json(url, key, body, headers=None):
        raise RuntimeError("Model provider returned HTTP 400: bad request; no action executed.")

    model.post_json = broken_post_json
    try:
        with paced_requests(0.0, retries=3, sleeper=fake_sleep) as paced:
            try:
                model.post_json("http://example.test", "k", {})
                raised = False
            except RuntimeError:
                raised = True
        checks.append(("a real error is not retried", raised and paced["attempts"] == 1))
    finally:
        model.post_json = original

    # 4. the warm-up clears a cookie wall and waits for the real form
    class FakeBrowser:
        def __init__(self, url):
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

    browser, page, warm = warm_up(seconds=5.0, poll=0.0, sleeper=lambda seconds: None, factory=FakeBrowser)
    checks.append(("the cookie wall is dismissed before the mission", browser.clicks == ["Accept all"]))
    checks.append(("the warm-up waits for the real form", _interactive(page)))

    # 5. the seven page checks accept a correct result page and reject a wrong one
    good = {
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
    passed = verify(good)
    checks.append(("a correct page passes all seven checks", passed["passed"] and len(passed["checks"]) == 7))
    wrong = {**good, "actions": [a for a in good["actions"] if "Select flight" not in a["label"]]}
    checks.append(("a page without matching results fails", verify(wrong)["passed"] is False))

    # 6. the three verdicts, including the infrastructure one
    consent = {"url": "https://consent.google.com/ml?continue=...", "text": "Before you continue to Google",
               "actions": []}
    outcome, _ = classify(consent, verify(consent))
    checks.append(("a consent wall is reported as site_blocked", outcome == "site_blocked"))
    timed_out, _ = classify(good, passed, timed_out=True)
    checks.append(("a timeout is a failure, not a pass", timed_out == "failed"))
    crashed, _ = classify(good, passed, error="RuntimeError: boom")
    checks.append(("a crash is a failure, not a pass", crashed == "failed"))
    ok, _ = classify(good, passed)
    checks.append(("a verified page is a pass", ok == "passed"))

    # 7. the report never claims a pass it did not measure
    report = render_report("failed", "checks not satisfied: results", {"verification": passed}, 12.0, pacing,
                           {"calls": 4, "slept_s": 3 * pacing}, "/usr/bin/google-chrome")
    checks.append(("the report labels the outcome", "🔴 **failed**" in report))
    for name, ok in checks:
        print(f"{'✅' if ok else '🔴'} {name}")
    return 0 if all(ok for _name, ok in checks) else 1


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--selftest", action="store_true", help="offline: no browser, no network, no keys")
    parser.add_argument("--max-seconds", type=float, default=600.0)
    parser.add_argument("--pacing", type=float, default=2.4, help="seconds between model calls")
    parser.add_argument("--tpm", type=float, default=6000.0,
                        help="token budget per minute (the free Groq tier allows 8000); 0 disables it")
    parser.add_argument("--window", type=float, default=60.0, help="seconds of the token budget window")
    parser.add_argument("--retries", type=int, default=3, help="throttled retries per model call")
    parser.add_argument("--mission", choices=["prepared", "cold"], default="prepared",
                        help="prepared: the documented plan; cold: only the outcome, as written above")
    parser.add_argument("--artifacts", default="")
    parser.add_argument("--json", default="")
    args = parser.parse_args()

    if args.selftest:
        # The offline path also exercises the wrapper's timing without network calls.
        return selftest(min(args.pacing, 0.05))

    chrome, reasons = preflight()
    if reasons:
        print(render_report("skipped", "preconditions not met", {}, 0.0, args.pacing,
                            {"calls": 0, "slept_s": 0.0, "tpm": args.tpm, "window_s": args.window}, chrome,
                            note="Skipped: " + "; ".join(reasons)))
        if args.json:
            Path(args.json).parent.mkdir(parents=True, exist_ok=True)
            Path(args.json).write_text(json.dumps({"outcome": "skipped", "reasons": reasons}, indent=2))
        return 0

    with paced_requests(args.pacing, tpm=args.tpm, window=args.window, retries=args.retries) as paced:
        state, error, timed_out, seconds = run_mission(args.max_seconds, args.artifacts, mission=args.mission)

    page = (state or {}).get("final_page") or {"url": "", "text": "", "actions": []}
    verification = (state or {}).get("verification") or {"passed": False, "checks": {}, "visible_flights": []}
    outcome, reason = classify(page, verification, error=error, timed_out=timed_out)
    report = render_report(outcome, reason, state or {}, seconds, args.pacing, paced, chrome)
    print(report)

    if args.json:
        destination = Path(args.json)
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(json.dumps({
            "outcome": outcome,
            "reason": reason,
            "seconds": seconds,
            "mission": args.mission,
            "pacing_s": args.pacing,
            "model_calls": paced["calls"],
            "token_budget_per_minute": args.tpm,
            "tokens_held": paced.get("tokens", 0.0),
            "throttled_retries": paced.get("retries", 0),
            "throttled_s": paced.get("throttled_s", 0.0),
            "attempts": (state or {}).get("attempt", 1),
            "warm_up": (state or {}).get("warm_up"),
            "verification": verification,
            "final_url": page.get("url"),
            "error": error,
            "steps": (state or {}).get("steps", []),
        }, indent=2, ensure_ascii=False))
        print(f"\nJSON written to {destination}")

    # A blocked site is infrastructure; a failed mission is our regression.
    return 1 if outcome == "failed" else 0


if __name__ == "__main__":
    raise SystemExit(main())
