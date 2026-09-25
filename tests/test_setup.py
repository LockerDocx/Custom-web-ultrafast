"""Contracts for the zero-config setup: one free key runs the whole agent.

The point of these tests is Occam's razor applied to setup: a user pastes one
key and everything else (three roles, their providers and their models) is
derived — without giving up the measured-best arrangement when both free keys
are present.
"""

import os

import pytest

from jev_ultrafast import firefox, model, parameters, providers

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
    assert "One free key runs the whole agent" in message
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
    assert "No API key for the policy role" in str(error.value) and "GROQ_API_KEY" in str(error.value)


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
    env_file.write_text("# settings\nGROQ_API_KEY=\nNVIDIA_API_KEY=\n")
    ok = providers.ensure_configured(
        prompt=lambda _question: "gsk_pasted",
        notify=printed.append,
        path=env_file,
        interactive=True,
    )
    assert ok is True
    saved = env_file.read_text()
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
