"""Contracts for the zero-config setup: one free key runs the whole agent.

The point of these tests is Occam's razor applied to setup: a user pastes one
key and everything else (three roles, their providers and their models) is
derived — without giving up the measured-best arrangement when both free keys
are present.
"""

import json
import os
import socket
import threading

import pytest

from jev_ultrafast import firefox, model, parameters, providers


class _StubServer:
    """A bridge that binds nothing: the test only cares about main()'s flow."""

    def __init__(self, port=0, token=None):
        self.port = port
        self.runner = None

    def start(self):
        pass




ALL_KEYS = (
    "GROQ_API_KEY", "NVIDIA_API_KEY", "OPENAI_API_KEY", "ANTHROPIC_API_KEY", "OPENROUTER_API_KEY",
    "DEEPSEEK_API_KEY", "TOGETHER_API_KEY", "MISTRAL_API_KEY", "XAI_API_KEY", "GEMINI_API_KEY",
    "TYPESAFE_API_KEY", "POLICY_API_KEY", "PLANNER_API_KEY", "TEXT_MODEL_API_KEY",
)


@pytest.fixture
def clean_env(monkeypatch):
    """Nothing configured: the state of a fresh install."""
    for name in ALL_KEYS + (
        "POLICY_PROVIDER", "POLICY_BASE_URL", "POLICY_MODEL",
        "PLANNER_PROVIDER", "PLANNER_BASE_URL", "PLANNER_MODEL",
        "TEXT_MODEL_PROVIDER", "TEXT_MODEL_BASE_URL", "TEXT_MODEL",
    ):
        monkeypatch.delenv(name, raising=False)
    yield monkeypatch


def test_one_groq_key_runs_all_three_roles(clean_env):
    clean_env.setenv("GROQ_API_KEY", "gsk_test")
    assert providers.selection_for("policy") == ("groq", "openai/gpt-oss-20b")
    assert providers.selection_for("text") == ("groq", "openai/gpt-oss-20b")
    # the planner gets the strongest model of that provider, not the executor's
    assert providers.selection_for("planner") == ("groq", "openai/gpt-oss-120b")
    assert providers.planner_enabled() is True

    provider = providers.resolve("policy")  # the real path a request takes
    assert provider["name"] == "groq" and provider["key"] == "gsk_test"
    assert provider["model"] == "openai/gpt-oss-20b" and provider["base_url"].startswith("https://api.groq.com")


def test_both_free_keys_get_the_measured_best_split(clean_env):
    clean_env.setenv("GROQ_API_KEY", "gsk_test")
    clean_env.setenv("NVIDIA_API_KEY", "nvapi-test")
    # NVIDIA plans once per mission; Groq executes every step (~280 ms).
    assert providers.selection_for("planner") == ("nvidia", "z-ai/glm-5.3")
    assert providers.selection_for("policy") == ("groq", "openai/gpt-oss-20b")
    assert providers.selection_for("text") == ("groq", "openai/gpt-oss-20b")


def test_one_nvidia_key_runs_all_three_roles(clean_env):
    clean_env.setenv("NVIDIA_API_KEY", "nvapi-test")
    assert providers.selection_for("planner") == ("nvidia", "z-ai/glm-5.3")
    assert providers.selection_for("policy") == ("nvidia", "openai/gpt-oss-20b")
    assert providers.selection_for("text") == ("nvidia", "openai/gpt-oss-20b")
    assert providers.resolve("text")["name"] == "nvidia"


def test_no_key_at_all_says_exactly_what_to_do(clean_env):
    assert providers.selection_for("policy") == ("", "")
    assert providers.planner_enabled() is False
    with pytest.raises(ValueError) as error:
        providers.resolve("policy")
    message = str(error.value)
    assert "One free key covers all three roles" in message
    assert providers.ROLE_LABELS["policy"] in message  # named the way the panel names it
    assert "GROQ_API_KEY" in message and "console.groq.com/keys" in message


def test_explicit_configuration_always_wins(clean_env):
    clean_env.setenv("GROQ_API_KEY", "gsk_test")
    clean_env.setenv("NVIDIA_API_KEY", "nvapi-test")
    clean_env.setenv("POLICY_PROVIDER", "deepseek")
    clean_env.setenv("POLICY_MODEL", "deepseek-reasoner")
    assert providers.selection_for("policy") == ("deepseek", "deepseek-reasoner")
    # and a role left alone still derives
    assert providers.selection_for("text") == ("groq", "openai/gpt-oss-20b")


def test_a_provider_alone_implies_its_documented_models(clean_env):
    """Choosing a provider without a model must not be a dead end."""
    clean_env.setenv("NVIDIA_API_KEY", "nvapi-test")
    clean_env.setenv("POLICY_PROVIDER", "nvidia")
    assert providers.selection_for("policy") == ("nvidia", "openai/gpt-oss-20b")
    assert providers.resolve("policy")["model"] == "openai/gpt-oss-20b"


def test_an_explicit_provider_without_a_key_still_fails_loudly(clean_env):
    clean_env.setenv("POLICY_PROVIDER", "groq")  # but no GROQ_API_KEY anywhere
    with pytest.raises(ValueError) as error:
        providers.resolve("policy")
    assert "No API key for the Executor role" in str(error.value) and "GROQ_API_KEY" in str(error.value)


def test_the_sidebar_shows_what_actually_runs(clean_env):
    """The panel must never disagree with the agent (they share one source)."""
    clean_env.setenv("GROQ_API_KEY", "gsk_test")
    clean_env.setenv("NVIDIA_API_KEY", "nvapi-test")
    selection = parameters.current_selection()
    assert selection["planner"]["provider"] == "nvidia"
    assert selection["planner"]["model"] == "z-ai/glm-5.3"
    assert selection["policy"]["provider"] == "groq"
    assert selection["policy"]["schema"]["parameters"]  # the real per-model surface
    assert parameters.model_for("text") == ("groq", "openai/gpt-oss-20b")


def test_the_planner_runs_out_of_the_box(clean_env):
    clean_env.setenv("GROQ_API_KEY", "gsk_test")
    config = model.planning_config()  # None would mean the old single-goal loop
    assert config is not None and config["name"] == "groq"


def test_the_self_test_covers_every_derived_role(clean_env, monkeypatch):
    clean_env.setenv("GROQ_API_KEY", "gsk_test")
    checked = []

    def fake_check_providers():
        checked.extend(providers.selection_for(role)[0] or role for role in ("planner", "policy", "text"))
        return {}

    monkeypatch.setattr(firefox, "check_providers", fake_check_providers)
    firefox.check_providers()
    assert checked == ["groq", "groq", "groq"]


# ── the single setup step: paste one key ─────────────────────────────────────


def test_a_pasted_key_is_saved_to_env(clean_env, tmp_path):
    printed = []
    env_file = tmp_path / ".env"
    env_file.write_text("# settings\nGROQ_API_KEY=\nNVIDIA_API_KEY=\n", encoding="utf-8")
    ok = providers.ensure_configured(
        prompt=lambda _question: "gsk_pasted",
        notify=printed.append,
        path=env_file,
        interactive=True,
    )
    assert ok is True
    saved = env_file.read_text(encoding="utf-8")
    assert "GROQ_API_KEY=gsk_pasted" in saved
    assert saved.count("GROQ_API_KEY") == 1  # replaced in place, not appended twice
    assert os.environ["GROQ_API_KEY"] == "gsk_pasted"  # and usable right away
    assert any("Saved to" in line for line in printed)


def test_skipping_the_prompt_prints_the_instructions(clean_env, tmp_path):
    printed = []
    ok = providers.ensure_configured(
        prompt=lambda _question: "", notify=printed.append, path=tmp_path / ".env", interactive=True
    )
    assert ok is False
    assert any("console.groq.com/keys" in line for line in printed)
    assert not (tmp_path / ".env").exists()


def test_no_prompt_when_nothing_is_interactive(clean_env, tmp_path, capsys):
    """CI and scripts must never block on a keyboard."""
    called = []
    ok = providers.ensure_configured(
        prompt=lambda question: called.append(question), notify=print, path=tmp_path / ".env", interactive=False
    )
    assert ok is False and called == []
    assert "GROQ_API_KEY" in capsys.readouterr().out


def test_an_already_configured_agent_is_never_asked(clean_env, tmp_path):
    clean_env.setenv("GROQ_API_KEY", "gsk_test")
    called = []
    assert providers.ensure_configured(
        prompt=lambda question: called.append(question), notify=print, path=tmp_path / ".env", interactive=True
    )
    assert called == []


def test_typesafe_key_also_counts_as_configured(clean_env):
    clean_env.setenv("TYPESAFE_API_KEY", "ts_test")
    assert providers.is_configured() is True


# ── the Firefox flow: the sidebar is the setup surface ───────────────────────


def _live_bridge(tmp_path, monkeypatch):
    """A real bridge on an ephemeral port, writing .env inside tmp_path."""
    from tests.test_firefox import FakeExtension  # the extension-side WebSocket client

    monkeypatch.chdir(tmp_path)
    provider_layer = providers
    provider_layer.save_key.__globals__["os"].environ.pop("JEV_ENV_FILE", None)
    server = firefox.BridgeServer(port=0)
    server.runner = firefox.TaskRunner(server)
    server.start()
    return server, FakeExtension(server.port)


def test_a_key_pasted_in_the_sidebar_configures_the_host(clean_env, tmp_path, monkeypatch):
    """The whole graphical setup: hello → paste key → saved, derived, announced."""
    server, ext = _live_bridge(tmp_path, monkeypatch)
    try:
        ext.send({"type": "hello"})
        welcome = ext.recv()
        assert welcome["type"] == "welcome" and welcome["ok"] is True
        assert welcome["state"]["setup"]["configured"] is False

        ext.send({"type": "setup.key", "variable": "GROQ_API_KEY", "value": "gsk_from_firefox"})
        frames = []
        for _ in range(8):
            try:
                frames.append(ext.recv(timeout=5))
            except (TimeoutError, socket.timeout):
                break
            if any(
                frame.get("type") == "state" and frame["state"]["setup"]["configured"] is True for frame in frames
            ) and any(frame.get("type") == "notice" for frame in frames):
                break
        notices = [frame for frame in frames if frame.get("type") == "notice"]
        assert notices and "GROQ_API_KEY" in notices[0]["message"], frames

        # saved where every other path reads it
        assert (tmp_path / ".env").read_text(encoding="utf-8").strip() == "GROQ_API_KEY=gsk_from_firefox"
        assert providers.selection_for("planner") == ("groq", "openai/gpt-oss-120b")

        # the sidebar is told the new state, and the key never travels back
        assert not any("gsk_from_firefox" in json.dumps(frame) for frame in frames)
        assert any(
            frame.get("type") == "state" and frame["state"]["setup"]["configured"] is True for frame in frames
        ), [frame.get("type") for frame in frames]
    finally:
        ext.close()
        server.close()


def test_a_bad_paste_answers_with_the_reason_and_touches_nothing(clean_env, tmp_path, monkeypatch):
    server, ext = _live_bridge(tmp_path, monkeypatch)
    try:
        ext.send({"type": "hello"})
        ext.recv()
        ext.send({"type": "setup.key", "variable": "GROQ_API_KEY", "value": "not a key with spaces"})
        while True:
            message = ext.recv(timeout=5)
            if message.get("type") == "error":
                assert "does not look like an API key" in message["message"]
                break
        assert not (tmp_path / ".env").exists()
        assert providers.is_configured() is False
    finally:
        ext.close()
        server.close()


def test_the_host_starts_without_a_key_and_points_at_the_sidebar(clean_env, tmp_path, monkeypatch, capsys):
    """Double-click with no key: no prompt in the terminal, no early exit."""
    asked = []
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("builtins.input", lambda *a: asked.append(a) or "")
    class Stop(threading.Event):
        def wait(self, *_args, **_kwargs):
            raise KeyboardInterrupt

    class Threading:
        """The real module, with only its blocking wait replaced."""

        Event = Stop

        def __getattr__(self, name):
            return getattr(threading, name)

    monkeypatch.setattr(firefox, "threading", Threading())
    monkeypatch.setattr(firefox, "BridgeServer", _StubServer)
    firefox.main()  # returns instead of waiting forever

    printed = capsys.readouterr().out
    assert "open the agent sidebar" in printed
    assert "Policy model" not in printed  # nothing configured yet
    assert asked == []  # never asked anything on the command line


# ── contracts between the extension and the host (no browser needed) ─────────


def _read(path):
    from pathlib import Path

    return Path(path).read_text(encoding="utf-8")


def test_every_message_the_extension_sends_is_understood_by_the_host():
    """The sidebar is the setup surface now: a typo in a message type would be silent."""
    import re

    sent = set(re.findall(r'send\(\{\s*type:\s*"([^"]+)"', _read("extension/background.js")))
    routed = set()
    for chunk in re.findall(r'kind (?:==|in) (\{[^}]*\}|"[^"]+")', _read("jev_ultrafast/firefox.py")):
        routed.update(re.findall(r'"([^"]+)"', chunk))
    assert sent, "no message types found - did background.js change shape?"
    assert sent <= routed, f"the host does not route: {sorted(sent - routed)}"


def test_every_command_the_sidebar_uses_is_relayed_by_the_background_script():
    import re

    used = set(re.findall(r'cmd:\s*"([^"]+)"', _read("extension/sidebar/sidebar.js")))
    relayed = set(re.findall(r'message\.cmd === "([^"]+)"', _read("extension/background.js")))
    assert used <= relayed, f"the background script does not relay: {sorted(used - relayed)}"


def test_the_setup_form_only_uses_elements_that_exist():
    import re

    html_ids = set(re.findall(r'id="([^"]+)"', _read("extension/sidebar/sidebar.html")))
    js_ids = set(re.findall(r'\$\("([^"]+)"\)', _read("extension/sidebar/sidebar.js")))
    assert js_ids <= html_ids, f"the sidebar asks for elements that do not exist: {sorted(js_ids - html_ids)}"


def test_background_and_host_agree_on_where_the_agent_listens():
    """The extension's default port must be the bridge's default port."""
    import re

    assert re.search(r'const DEFAULT_PORT = (\d+)', _read("extension/background.js")).group(1) == str(
        firefox.DEFAULT_PORT
    )


class _RecordingBridge:
    def __init__(self):
        self.sent = []

    def send(self, message):
        self.sent.append(message)

    def broadcast(self, message):
        self.sent.append(message)


def test_a_verdict_from_before_the_key_is_never_published(clean_env, tmp_path, monkeypatch):
    """The classic race: a check starts with no key, the key arrives, the check answers anyway."""
    import time

    calls = []

    def slow_check():
        calls.append(len(calls) + 1)
        time.sleep(0.4)  # long enough for the key to be saved mid-flight
        return {"policy": {"role": "policy", "ok": len(calls) > 1, "detail": f"call {len(calls)}"}}

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(firefox, "check_providers", slow_check)
    bridge = _RecordingBridge()
    runner = firefox.TaskRunner(bridge)

    threading.Thread(target=runner.run_provider_check, daemon=True).start()
    time.sleep(0.1)  # the first check is running now
    runner.handle_setup_key("GROQ_API_KEY", "gsk_arrived_late")

    deadline = time.time() + 10
    while time.time() < deadline and runner.provider_check is None:
        time.sleep(0.05)
    assert runner.provider_check is not None, "no verdict was published at all"
    assert runner.provider_check["policy"]["detail"] == "call 2", "a stale verdict was published"
    assert len(calls) == 2, "the fresh check did not run"
    assert any("Saved GROQ_API_KEY" in m.get("message", "") for m in bridge.sent if m.get("type") == "notice")
