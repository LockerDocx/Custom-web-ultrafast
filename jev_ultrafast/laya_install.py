"""Install Laya for the user, once, in the background — it is on by default.

Why it is default-on and not an extra: the two decisions Laya answers — which loop a
mission needs, and which procedural package should guide it — are *already* local without
it (a keyword router), so this is a quality choice, not a speed one, and the honest
numbers are in the CI battery: with real weights Laya decides on its own in 6 of 14
missions (browser/es, browser/de, browser/fr, and the skill picks), abstains on the rest
because its calibrated confidence stays below the gate, and the keyword fallback answers
those — 14/14 correct together, 195 ms per decision on a 2-core CPU, no key, no network
after the weights are downloaded. What it adds over pure keywords is language: the
keyword lists are English-and-Spanish, decided per line, while Laya reads the mission.

Downloading it is one thing, so the agent does it for you on the first normal start;
nothing about the install is hidden, and it can be declined:

    JEV_LAYA=off          don't use Laya at all (the installer is not run either)
    JEV_LAYA_AUTO=off     keep using Laya if it is there, but never install it
    JEV_LAYA_AUTO=retry   try the install again (it is not retried on every start)

Everything here is fail-safe: if pip is missing, the machine is offline, or the package
cannot be installed, the agent says so in the sidebar and runs exactly as before.
"""

import importlib.util
import json
import os
import subprocess
import sys
import threading
import time

from . import laya_local

# The default PyPI torch on Linux bundles CUDA (~2.5 GB download); the CPU build is ~10x
# smaller and is all Laya needs. macOS wheels on PyPI are already CPU/MPS-only.
CPU_TORCH_INDEX = "https://download.pytorch.org/whl/cpu"
TORCH_PLATFORMS_USING_CPU_INDEX = ("linux", "win32")
LAYA_REQUIREMENT = "laya>=0.3,<1"
INSTALL_TIMEOUT = 1800.0  # a slow connection must not be called a failure at 5 minutes
OUTCOME_FILE = "laya-install.json"

_installing = False
_last_outcome = None
_lock = threading.Lock()
_thread = None


def auto_policy():
    """'on', 'off' or 'retry' — what the user asked for, with 'on' as the default."""
    value = (os.environ.get("JEV_LAYA_AUTO") or "on").strip().lower()
    if value in {"off", "0", "no", "false"}:
        return "off"
    if value in {"retry", "force", "again"}:
        return "retry"
    return "on"


def marker_path():
    """Next to the key file, so one app has exactly one record of what it did."""
    from . import providers

    return providers.env_file_path().with_name(OUTCOME_FILE)


def recorded():
    """What the last attempt did, or None. Never re-installs what already succeeded."""
    try:
        data = json.loads(marker_path().read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001 - an unreadable record is not a reason to install twice
        return None
    return data if isinstance(data, dict) else None


def _record(outcome, detail):
    global _last_outcome
    _last_outcome = {"outcome": outcome, "detail": str(detail)[:400], "when": int(time.time())}
    try:
        marker_path().write_text(json.dumps(_last_outcome, ensure_ascii=False), encoding="utf-8")
    except OSError:
        pass  # a body that cannot write the record still installs correctly


def user_started():
    """Is this a normal user start, rather than a test run or a pipeline?

    Downloading ~1 GB in someone's CI, or in the middle of a test suite, is not a favour:
    it was measured here, and the install landed inside `pytest` and took the machine's
    memory with it. A real start is the only place the download is wanted.
    """
    if "pytest" in sys.modules or "unittest" in sys.modules:
        return False
    if (os.environ.get("CI") or "").strip().lower() not in {"", "0", "false", "no"}:
        return False
    return True


def can_install():
    """(bool, why not) — a real environment check, not an assumption.

    Installing into the system interpreter is someone else's machine to break, so this
    only touches a virtualenv (the starter creates one) or a dedicated user prefix.
    """
    if not laya_local.enabled():
        return False, "Laya is turned off (JEV_LAYA=off)"
    if importlib.util.find_spec("pip") is None:
        return False, "pip is not available in this Python"
    in_venv = sys.prefix != getattr(sys, "base_prefix", sys.prefix)
    if not in_venv and os.environ.get("JEV_LAYA_AUTO") != "force":
        return False, (
            "this Python is not a virtualenv, so nothing was installed — run "
            "install-laya.sh (or pip install -e \".[laya]\") if you want Laya here"
        )
    return True, ""


def pip_steps():
    """The exact commands, in order. CPU torch first, so Laya does not pull the CUDA build."""
    steps = []
    if sys.platform in TORCH_PLATFORMS_USING_CPU_INDEX:
        steps.append([sys.executable, "-m", "pip", "install", "--quiet", "torch", "--index-url", CPU_TORCH_INDEX])
    steps.append([sys.executable, "-m", "pip", "install", "--quiet", LAYA_REQUIREMENT])
    return steps


def wanted():
    """(bool, why not) — should this start install Laya?"""
    if laya_local.available():
        return False, "already installed"
    ok, why = can_install()
    if not ok:
        return False, why
    policy = auto_policy()
    if policy == "off":
        return False, "automatic install is off (JEV_LAYA_AUTO=off)"
    if policy == "retry":
        return True, ""
    previous = recorded()
    if previous and previous.get("outcome") == "installed":
        return False, "installed earlier and not importable — reinstall with install-laya.sh"
    if previous and previous.get("outcome") == "failed":
        return False, (
            "a previous attempt failed, so it is not retried on every start — "
            "run install-laya.sh, or JEV_LAYA_AUTO=retry"
        )
    return True, ""


def install(on_event=None):
    """Run the install and return (ok, detail). Reports each step as it starts."""
    global _installing
    note = on_event or (lambda *_a, **_k: None)
    with _lock:
        if _installing:
            return False, "an install is already running"
        _installing = True
    try:
        for step in pip_steps():
            note(f"Installing the local decision engine (Laya): {' '.join(step[2:5])}…")
            done = subprocess.run(
                step,
                capture_output=True,
                text=True,
                timeout=INSTALL_TIMEOUT,
                check=False,
            )
            if done.returncode != 0:
                detail = (done.stderr or done.stdout or "").strip().splitlines()
                reason = detail[-1] if detail else f"pip exited with {done.returncode}"
                _record("failed", reason)
                note(f"Laya could not be installed: {reason}")
                return False, reason
        # The import cache still has the pre-install answer for this interpreter; ask again
        # in a fresh one so the verdict is the new truth, not the old one.
        probe = subprocess.run(
            [sys.executable, "-c", "import laya, sys; print('ok')"],
            capture_output=True,
            text=True,
            timeout=120,
            check=False,
        )
        if probe.returncode != 0 or "ok" not in probe.stdout:
            reason = (probe.stderr or "").strip().splitlines()[-1:] or ["the package does not import"]
            _record("failed", reason[0])
            note(f"Laya was installed but does not import: {reason[0]}")
            return False, reason[0]
        _record("installed", "installed by the agent on first start")
        note("Laya is installed: decisions are answered locally from now on.")
        return True, "installed"
    except Exception as error:  # noqa: BLE001 - any install failure must leave the agent usable
        _record("failed", str(error))
        note(f"Laya could not be installed: {str(error)[:200]}")
        return False, str(error)[:200]
    finally:
        _installing = False


def ensure_async(on_event=None, on_done=None):
    """Start the install in the background if it is wanted; never blocks a start."""
    global _thread
    if not user_started():
        # Tests and pipelines are not a user starting the agent: nothing is downloaded there.
        if on_done:
            on_done(False, "not a normal start")
        return False
    ok, why = wanted()
    if not ok:
        if why not in {"already installed"}:
            (on_event or (lambda *_a, **_k: None))(f"Laya: {why}.")
        if on_done:
            on_done(False, why)
        return False
    if _thread is not None and _thread.is_alive():
        return False

    def run():
        ok, detail = install(on_event=on_event)
        if ok:
            laya_local.warm()  # load the weights now, so the first decision is already fast
        if on_done:
            on_done(ok, detail)

    _thread = threading.Thread(target=run, daemon=True, name="laya-install")
    _thread.start()
    return True


def state():
    """What the sidebar shows about the local engine — the same words the logs use."""
    installed = laya_local.available()
    ready = laya_local._engine is not None  # noqa: SLF001 - same package, one source of truth
    if not laya_local.enabled():
        return {
            "enabled": False,
            "installed": installed,
            "ready": ready,
            "installing": False,
            "status": "off (JEV_LAYA=off)",
        }
    if _installing:
        status = "installing in the background…"  # noqa: RUF001 - the panel's own ellipsis
    elif ready:
        status = laya_local.status()
    elif installed:
        status = laya_local.status()
    else:
        ok, why = wanted()
        status = "installing in the background…" if ok else why
    return {
        "enabled": True,
        "installed": installed,
        "ready": ready,
        "installing": _installing,
        "status": status,
    }


def main():
    """`python -m jev_ultrafast.laya_install` — the manual path, used by install-laya.sh."""
    print("Laya: the open decision engine, 100% local.")
    if laya_local.available():
        print("Already installed. Nothing to do.")
        return 0
    ok, why = can_install()
    if not ok:
        print(f"Cannot install here: {why}")
        return 1
    for step in pip_steps():
        print(f"$ {' '.join(step)}", flush=True)
    ok, detail = install(on_event=lambda line: print(f"  {line}", flush=True))
    if ok:
        print("\nDone. Restart the host so it loads the engine.")
        return 0
    print(f"\n[!] Installation failed: {detail}")
    print("The agent still works without Laya, only slower (each decision is a cloud call).")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
