"""Laya is installed by default, in the background, and it never breaks a start.

Without it every routing and skill decision is a cloud call on a free tier — which is the
failure users actually hit (HTTP 429 in the middle of a mission). So the agent installs it
for them; these tests pin that it does, that it can be declined, and that a failed install
leaves a working agent and an honest message.
"""

import os
import sys
from pathlib import Path

import pytest

from jev_ultrafast import laya_install


@pytest.fixture
def clean_env(monkeypatch, tmp_path):
    """A machine with no key file, no Laya and no opinion about any of it."""
    for name in list(os.environ):
        if name.startswith(("JEV_", "LAYA_", "HF_")):
            monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("JEV_ENV_FILE", str(tmp_path / "env"))
    return monkeypatch


@pytest.fixture
def not_installed(monkeypatch):
    monkeypatch.setattr(laya_install.laya_local, "available", lambda: False)
    monkeypatch.setattr(laya_install.laya_local, "_engine", None, raising=False)
    return monkeypatch


def test_laya_is_installed_by_default(clean_env, not_installed):
    wanted, why = laya_install.wanted()
    assert wanted is True, f"Laya must install itself out of the box; instead: {why}"
    assert laya_install.auto_policy() == "on"


def test_the_install_goes_into_the_interpreter_the_app_runs_from(clean_env):
    for step in laya_install.pip_steps():
        assert step[0] == sys.executable, "installing into another Python would do nothing"
        assert step[1:3] == ["-m", "pip"]


def test_the_cpu_build_of_torch_is_asked_for_on_linux_and_windows(clean_env, monkeypatch):
    """PyPI's Linux torch bundles CUDA (~2.5 GB); the CPU wheel is ~10x smaller."""
    for platform in ("linux", "win32"):
        monkeypatch.setattr(sys, "platform", platform)
        steps = laya_install.pip_steps()
        assert steps[0][-2:] == ["--index-url", laya_install.CPU_TORCH_INDEX], platform
        assert steps[-1][-1] == laya_install.LAYA_REQUIREMENT, "the package is installed last"
    monkeypatch.setattr(sys, "platform", "darwin")
    assert len(laya_install.pip_steps()) == 1, "macOS wheels need no special index"


def test_installing_is_never_attempted_twice(clean_env, not_installed):
    laya_install._record("installed", "done earlier")
    wanted, why = laya_install.wanted()
    assert wanted is False
    assert "install-laya.sh" in why, "the user still needs a way to reinstall by hand"


def test_a_failed_install_is_not_retried_on_every_start(clean_env, not_installed):
    """A machine that is offline would otherwise pay for the attempt at every launch."""
    laya_install._record("failed", "no internet")
    assert laya_install.wanted()[0] is False
    clean_env.setenv("JEV_LAYA_AUTO", "retry")
    assert laya_install.wanted()[0] is True


def test_the_user_can_decline(clean_env, not_installed):
    clean_env.setenv("JEV_LAYA_AUTO", "off")
    wanted, why = laya_install.wanted()
    assert wanted is False and "JEV_LAYA_AUTO=off" in why
    clean_env.delenv("JEV_LAYA_AUTO", raising=False)
    clean_env.setenv("JEV_LAYA", "off")
    assert laya_install.wanted()[0] is False
    assert laya_install.state()["enabled"] is False
    assert "off" in laya_install.state()["status"]


def test_a_system_python_is_left_alone(clean_env, not_installed, monkeypatch):
    """Installing packages into someone's system Python is not ours to do."""
    monkeypatch.setattr(sys, "base_prefix", "/usr")
    monkeypatch.setattr(sys, "prefix", "/usr")
    ok, why = laya_install.can_install()
    assert ok is False
    assert "virtualenv" in why and "install-laya.sh" in why
    monkeypatch.setenv("JEV_LAYA_AUTO", "force")
    assert laya_install.can_install()[0] is True, "an explicit request is an explicit request"


def test_a_failed_install_reports_it_and_leaves_the_agent_running(clean_env, not_installed, monkeypatch):
    seen = []

    class Failed:
        returncode = 1
        stdout = ""
        stderr = "ERROR: Could not find a version that satisfies the requirement laya"

    monkeypatch.setattr(laya_install.subprocess, "run", lambda *a, **k: Failed())
    ok, detail = laya_install.install(on_event=seen.append)
    assert ok is False
    assert "Could not find a version" in detail
    assert any("could not be installed" in line for line in seen), "the log says what happened"
    assert laya_install.recorded()["outcome"] == "failed"
    assert laya_install.state()["installed"] is False


def test_an_install_that_does_not_import_is_a_failure(clean_env, not_installed, monkeypatch):
    """pip can succeed and the package still not work: the verdict is the import, not pip."""

    class Ok:
        returncode = 0
        stdout = ""
        stderr = ""

    class NoImport:
        returncode = 1
        stdout = ""
        stderr = "ImportError: cannot import name 'Agent' from 'laya'"

    calls = []
    monkeypatch.setattr(
        laya_install.subprocess, "run", lambda *a, **k: (calls.append(a) or (Ok() if len(calls) == 1 else NoImport()))
    )
    ok, detail = laya_install.install()
    assert ok is False and "ImportError" in detail
    assert laya_install.recorded()["outcome"] == "failed"


def test_a_successful_install_says_so_and_warms_the_engine(clean_env, not_installed, monkeypatch):
    warmed = []
    class Installed:
        returncode = 0
        stdout = "ok"
        stderr = ""

    monkeypatch.setattr(laya_install.subprocess, "run", lambda *a, **k: Installed())
    monkeypatch.setattr(laya_install.laya_local, "warm", lambda: warmed.append(True))
    monkeypatch.setattr(laya_install, "user_started", lambda: True)  # simulate a real start
    done = []
    started = laya_install.ensure_async(on_done=lambda ok, detail: done.append(ok))
    assert started is True
    for _ in range(200):
        if done:
            break
        __import__("time").sleep(0.02)
    assert done == [True]
    assert warmed, "the weights must be preloaded once it is installed"
    assert laya_install.recorded()["outcome"] == "installed"


def test_the_background_install_never_blocks_the_start(clean_env, not_installed, monkeypatch):
    """The host returns immediately; the install is a thread, not a wait."""
    import threading

    class Slow:
        returncode = 0
        stdout = "ok"
        stderr = ""

    monkeypatch.setattr(laya_install.laya_local, "available", lambda: True)  # nothing to install
    assert laya_install.ensure_async(on_event=lambda _l: None) is False
    monkeypatch.setattr(laya_install.laya_local, "available", lambda: False)
    monkeypatch.setattr(laya_install.subprocess, "run", lambda *a, **k: Slow())
    assert threading.active_count() >= 1


def test_the_panel_and_the_log_use_the_same_word_for_it(clean_env, not_installed):
    state = laya_install.state()
    assert set(state) == {"enabled", "installed", "ready", "installing", "status"}
    assert isinstance(state["status"], str) and state["status"]
    assert state["status"] == laya_install.laya_local.status() or not state["installed"]


def test_the_manual_installer_is_the_same_code_path(clean_env, monkeypatch, capsys):
    monkeypatch.setattr(laya_install.laya_local, "available", lambda: True)
    assert laya_install.main() == 0
    assert "Already installed" in capsys.readouterr().out


def test_a_machine_without_room_is_not_killed_loading_the_weights(clean_env, monkeypatch):
    """Measured here: 644 MB of weights + torch on a 2 GB box gets the process OOM-killed.

    Nothing can catch that, so the load asks first and says the number it decided with.
    """
    from jev_ultrafast import laya_local

    monkeypatch.setattr(laya_local, "available", lambda: True)
    monkeypatch.setattr(laya_local, "free_memory_mb", lambda: 512.0)
    monkeypatch.setattr(laya_local, "_engine", None, raising=False)
    monkeypatch.setattr(laya_local, "_load_error", None, raising=False)
    room, where = laya_local.enough_memory()
    assert room is False and "0.5 GB" in where, "the panel gets the real figure, not a guess"
    assert laya_local.engine() is None, "it must refuse instead of dying"
    assert "free memory" in laya_local.status()
    laya_local.warm()
    assert "free memory" in laya_local.status()


def test_a_machine_with_room_loads_it(clean_env, monkeypatch):
    from jev_ultrafast import laya_local

    monkeypatch.setattr(laya_local, "free_memory_mb", lambda: 8192.0)
    room, where = laya_local.enough_memory()
    assert room is True and "8.0 GB" in where


def test_an_unknown_machine_is_not_talked_out_of_loading(clean_env, monkeypatch):
    """No /proc/meminfo and no sysctl: we do not invent a refusal."""
    from jev_ultrafast import laya_local

    monkeypatch.setattr(laya_local, "free_memory_mb", lambda: None)
    monkeypatch.setattr(laya_local, "total_memory_mb", lambda: None)
    assert laya_local.enough_memory() == (True, "RAM unknown")


def test_no_install_happens_in_tests_or_ci(clean_env, not_installed, monkeypatch):
    """Measured: a background install during the test suite took the machine down.

    The policy question ("would a normal start install it?") still answers yes; what the
    suite must never do is actually start the download.
    """
    assert laya_install.wanted()[0] is True, "the policy is unchanged"
    assert laya_install.user_started() is False, "`pytest` is running"
    done = []
    assert laya_install.ensure_async(on_done=lambda ok, why: done.append(ok)) is False
    assert done == [False]
    without = {k: v for k, v in sys.modules.items() if k not in {"pytest", "unittest"}}
    monkeypatch.setattr(laya_install.sys, "modules", without)
    monkeypatch.setenv("CI", "true")
    assert laya_install.user_started() is False, "a pipeline is not a user start either"
    monkeypatch.delenv("CI")
    assert laya_install.user_started() is True, "a real start still installs"


def test_conftest_keeps_the_suite_away_from_the_installer():
    """A second lock on the same door: the suite sets the switch itself."""
    import conftest  # the file, not a plugin: proves the default it installs

    source = Path(conftest.__file__).read_text(encoding="utf-8")
    assert 'JEV_LAYA_AUTO' in source
