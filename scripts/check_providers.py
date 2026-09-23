"""Per-role model connectivity report — the same check the sidebar runs at startup.
Re-run it with a push to this file or from the repo's Actions tab (workflow_dispatch).

Usage:
    uv run --env-file .env python scripts/check_providers.py   # local, reads .env
    python scripts/check_providers.py                           # env already set

Prints a markdown table with one row per configured role (planner / policy /
text): model, latency, or the provider's exact error. Purely diagnostic: it
always exits 0 and never prints credentials.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from jev_ultrafast.firefox import check_providers, load_environment  # noqa: E402

# A spent allowance is not a broken model. Measured here: the text role answered 🔴 because
# the policy role had already spent the same model's daily tokens minutes earlier in the
# same check. The check is about connectivity and permissions, so a rate or quota limit is
# reported as its own state, named honestly, instead of as a failure.
LIMIT_MARKERS = ("HTTP 429", "HTTP 529", "rate limit", "tokens per day", "tokens per minute", "quota")


def state(entry):
    """One row's icon and text: ok, limited (capacity now), or failed (cannot be used)."""
    if entry["ok"]:
        return "🟢", f"ok · {entry['latency_ms']} ms"
    detail = entry["detail"].replace("|", "/")
    if any(marker.lower() in detail.lower() for marker in LIMIT_MARKERS):
        return "🟡", f"limitado ahora mismo · {detail}"
    return "🔴", detail


def main():
    load_environment()
    results = check_providers()
    print("### Model provider check\n")
    print("| Role | Model | Status |")
    print("| --- | --- | --- |")
    for entry in results.values():
        icon, text = state(entry)
        print(f"| {entry['role']} | `{entry['model'] or '—'}` | {icon} {text} |")


if __name__ == "__main__":
    main()
