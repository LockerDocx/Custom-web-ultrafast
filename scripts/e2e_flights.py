#!/usr/bin/env python3
"""End-to-end flights mission on the real Google Flights page, verified by page state.

This is the only test that exercises the whole stack against a live third-party site:
real Chrome through the CDP harness, the real policy/text providers, the real agent
loop, and an independent verification of the resulting page.

The mission is the documented demo — one-way Zurich to London, September 20 2026,
one adult, economy — and it never selects or books anything.

Design notes that matter on a CI runner:

- **Pacing.** Free provider tiers reject bursts. Every model call is spaced by
  `--pacing` seconds by wrapping `model.post_json` / `model.post_stream`, the single
  HTTP seam of the product, so the wrapper cannot be bypassed by a new call site.
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
import shutil
import sys
import time
from contextlib import contextmanager
from pathlib import Path
from urllib.parse import urlparse

sys.path.insert(0, str(Path(__file__).parent.parent))

from examples.flights import GOALS, URL, verify  # noqa: E402

BLOCK_MARKERS = (
    "before you continue", "consent", "captcha", "unusual traffic",
    "are you a robot", "accept all", "i agree", "recaptcha",
)


@contextmanager
def paced_requests(pacing):
    """Space out every model call through the product's single HTTP seam."""
    from jev_ultrafast import model

    original_json, original_stream = model.post_json, model.post_stream
    state = {"calls": 0, "slept_s": 0.0}

    def wait():
        if state["calls"]:
            time.sleep(pacing)
            state["slept_s"] += pacing
        state["calls"] += 1

    def post_json(url, key, body, headers=None):
        wait()
        return original_json(url, key, body, headers=headers)

    def post_stream(url, key, body, headers=None, on_delta=None):
        wait()
        return original_stream(url, key, body, headers=headers, on_delta=on_delta)

    model.post_json, model.post_stream = post_json, post_stream
    try:
        yield state
    finally:
        model.post_json, model.post_stream = original_json, original_stream


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


def preflight():
    """Every reason to skip, collected before a browser is opened."""
    reasons = []
    from jev_ultrafast import providers

    for role in ("policy", "text"):
        try:
            provider = providers.resolve(role)
            reasons.append(None) if False else None
            if provider is None:  # pragma: no cover - resolve never returns None
                reasons.append(f"{role}: no provider")
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


def run_mission(max_seconds, artifacts):
    """Run the live mission, bounded in time; returns (state, error, timed_out, seconds)."""
    from jev_ultrafast import Agent

    started = time.perf_counter()
    error, timed_out, last = None, False, None
    collected = []
    try:
        agent = Agent(URL, GOALS)
    except Exception as failure:  # noqa: BLE001 - a browser that will not start is a run failure
        return None, f"{type(failure).__name__}: {failure}", False, round(time.perf_counter() - started, 1)
    try:
        for state in agent.run():
            last = state
            step = state["history"][-1] if state["history"] else {}
            collected.append({
                "elapsed_ms": state["elapsed_ms"],
                "status": state["status"],
                "action": step.get("action"),
                "url": step.get("url"),
            })
            print(f"{state['elapsed_ms']:>7} ms  {state['status']:<10} {step.get('action', '')}", flush=True)
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
            if artifacts:
                folder = Path(artifacts)
                folder.mkdir(parents=True, exist_ok=True)
                (folder / "state.json").write_text(json.dumps(state, indent=2, ensure_ascii=False))
            result = state
        except Exception as failure:  # noqa: BLE001 - an unreadable page is still a result
            result = last or {"history": [], "error": f"{type(failure).__name__}: {failure}"}
            result.setdefault("final_page", {"url": "", "text": "", "actions": []})
            result["verification"] = {"passed": False, "checks": {}, "visible_flights": []}
        agent.close()
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
    lines += [
        f"- Wall clock: **{seconds:,.1f} s** · mission status: `{state.get('status', '—')}` · "
        f"actions: {len(state.get('history') or [])}",
        f"- Model calls: **{paced['calls']}** with {pacing:,.1f} s pacing ({paced['slept_s']:,.1f} s slept) · "
        f"Chrome: `{chrome or 'not found'}`",
        f"- Final URL: {state.get('final_page', {}).get('url', '—')}",
        "",
    ]
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
    if state.get("error"):
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

    # 2. the seven page checks accept a correct result page and reject a wrong one
    good = {
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
    passed = verify(good)
    checks.append(("a correct page passes all seven checks", passed["passed"] and len(passed["checks"]) == 7))
    wrong = {**good, "actions": [a for a in good["actions"] if "Select flight" not in a["label"]]}
    checks.append(("a page without matching results fails", verify(wrong)["passed"] is False))

    # 3. the three verdicts, including the infrastructure one
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

    # 4. the report never claims a pass it did not measure
    report = render_report("failed", "checks not satisfied: results", {"verification": passed}, 12.0, pacing,
                           {"calls": 4, "slept_s": 3 * pacing}, "/usr/bin/google-chrome")
    checks.append(("the report labels the outcome", "🔴 **failed**" in report))
    for name, ok in checks:
        print(f"{'✅' if ok else '🔴'} {name}")
    return 0 if all(ok for _name, ok in checks) else 1


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--selftest", action="store_true", help="offline: no browser, no network, no keys")
    parser.add_argument("--max-seconds", type=float, default=300.0)
    parser.add_argument("--pacing", type=float, default=2.4, help="seconds between model calls")
    parser.add_argument("--artifacts", default="")
    parser.add_argument("--json", default="")
    args = parser.parse_args()

    if args.selftest:
        # The offline path also exercises the wrapper's timing without network calls.
        return selftest(min(args.pacing, 0.05))

    chrome, reasons = preflight()
    if reasons:
        print(render_report("skipped", "preconditions not met", {}, 0.0, args.pacing,
                            {"calls": 0, "slept_s": 0.0}, chrome,
                            note="Skipped: " + "; ".join(reasons)))
        if args.json:
            Path(args.json).parent.mkdir(parents=True, exist_ok=True)
            Path(args.json).write_text(json.dumps({"outcome": "skipped", "reasons": reasons}, indent=2))
        return 0

    with paced_requests(args.pacing) as paced:
        state, error, timed_out, seconds = run_mission(args.max_seconds, args.artifacts)

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
            "pacing_s": args.pacing,
            "model_calls": paced["calls"],
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
