"""Contracts for the model/parameter layer (MVP-1).

The repair under test here: the schema is per model (dialect + capabilities +
family rules + probe results), not one global shape for every role.
"""

import json
import time

import pytest

from jev_ultrafast import discovery, parameters

ALL_ROLE_ENV = [env for pair in parameters.ROLE_MODEL_ENV.values() for env in pair]
ALL_PARAM_ENV = list(parameters.ROLE_PARAM_ENV.values())


@pytest.fixture(autouse=True)
def isolated_env(tmp_path, monkeypatch):
    """Empty role env vars + a temp config file; monkeypatch restores everything."""
    for name in ALL_ROLE_ENV + ALL_PARAM_ENV:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr(parameters, "CONFIG_PATH", tmp_path / "model-config.json")
    yield


def test_schema_covers_every_role_and_env():
    roles = {r["key"] for r in parameters.PARAMETER_SCHEMA["roles"]}
    assert roles == {"planner", "policy", "text"}
    assert set(parameters.ROLE_MODEL_ENV) == roles
    for role in roles:
        for param in parameters.PARAMETER_SCHEMA["parameters"]:
            assert (role, param) in parameters.ROLE_PARAM_ENV, f"missing env for {role}.{param}"
    assert parameters.PARAMETER_SCHEMA["parameters"]["temperature"]["max"] == 2


def test_presets_only_reference_known_roles_and_params():
    for key, preset in parameters.PRESETS.items():
        assert preset["label"], f"preset {key} needs a label"
        for role, params in preset["params"].items():
            assert role in parameters.ROLE_MODEL_ENV
            for name in params:
                assert name in parameters.PARAMETER_SCHEMA["parameters"]


def test_apply_params_sets_env_and_persists():
    applied = parameters.apply_params("planner", {"reasoning": "high", "temperature": 0.4})
    assert applied == {"reasoning": "high", "temperature": 0.4}
    import os

    assert os.environ["PLANNER_REASONING"] == "high"
    assert os.environ["PLANNER_TEMPERATURE"] == "0.4"
    saved = json.loads(parameters.CONFIG_PATH.read_text())
    assert saved["params"]["planner"] == {"reasoning": "high", "temperature": 0.4}


def test_apply_params_none_clears_the_value():
    import os

    parameters.apply_params("text", {"temperature": 0.9})
    assert os.environ.get("TEXT_MODEL_TEMPERATURE")
    parameters.apply_params("text", {"temperature": None})
    assert "TEXT_MODEL_TEMPERATURE" not in os.environ
    saved = json.loads(parameters.CONFIG_PATH.read_text())
    assert "temperature" not in saved["params"]["text"]


def test_apply_params_rejects_out_of_range_and_unknown():
    with pytest.raises(ValueError, match="between 0 and 2"):
        parameters.apply_params("policy", {"temperature": 3})
    with pytest.raises(ValueError, match="reasoning must be one of"):
        parameters.apply_params("policy", {"reasoning": "ultra"})
    with pytest.raises(ValueError, match="Unknown role"):
        parameters.apply_params("hacker", {"reasoning": "low"})
    with pytest.raises(ValueError, match="Unknown parameter"):
        parameters.apply_params("policy", {"telepathy": "on"})


def test_apply_preset_applies_every_role():
    parameters.apply_preset("coding")
    import os

    assert os.environ["PLANNER_REASONING"] == "high"
    assert os.environ["POLICY_TEMPERATURE"] == "0.2"
    assert os.environ["TEXT_MODEL_TEMPERATURE"] == "0.2"
    with pytest.raises(ValueError, match="Unknown preset"):
        parameters.apply_preset("turbo")


def test_apply_model_switches_provider_and_model():
    import os

    parameters.apply_model("text", "groq", "openai/gpt-oss-20b")
    assert os.environ["TEXT_MODEL_PROVIDER"] == "groq"
    assert os.environ["TEXT_MODEL"] == "openai/gpt-oss-20b"
    saved = json.loads(parameters.CONFIG_PATH.read_text())
    assert saved["models"]["text"] == {"provider": "groq", "model": "openai/gpt-oss-20b"}
    # colons are fine: Ollama tags look like qwen3.5:4b
    parameters.apply_model("text", "ollama", "qwen3.5:4b")
    assert os.environ["TEXT_MODEL"] == "qwen3.5:4b"
    with pytest.raises(ValueError):
        parameters.apply_model("text", "groq", "  ")
    with pytest.raises(ValueError):
        parameters.apply_model("text", "groq", "model with spaces")


def test_apply_saved_config_overrides_env_defaults():
    import os

    parameters.apply_model("planner", "nvidia", "z-ai/glm-5.3")
    parameters.apply_params("planner", {"reasoning": "medium"})
    # simulate a restart: env back to .env defaults, config file kept
    for name in ("PLANNER_PROVIDER", "PLANNER_MODEL", "PLANNER_REASONING"):
        os.environ.pop(name, None)
    os.environ["PLANNER_PROVIDER"] = "groq"
    os.environ["PLANNER_MODEL"] = "openai/gpt-oss-20b"
    parameters.apply_saved_config()
    assert os.environ["PLANNER_PROVIDER"] == "nvidia"
    assert os.environ["PLANNER_MODEL"] == "z-ai/glm-5.3"
    assert os.environ["PLANNER_REASONING"] == "medium"


def test_apply_saved_config_survives_broken_file(tmp_path):
    monkey = pytest.MonkeyPatch()
    monkey.setattr(parameters, "CONFIG_PATH", tmp_path / "broken.json")
    try:
        tmp_path.joinpath("broken.json").write_text("{not json")
        assert parameters.apply_saved_config() == {}
    finally:
        monkey.undo()


def test_current_selection_reports_display_and_params():
    import os

    parameters.apply_model("planner", "nvidia", "z-ai/glm-5.3")
    parameters.apply_params("planner", {"reasoning": "low"})
    selection = parameters.current_selection()
    assert selection["planner"]["provider"] == "nvidia"
    assert selection["planner"]["model"] == "z-ai/glm-5.3"
    assert selection["planner"]["display"] == "GLM 5.3"
    assert selection["planner"]["params"] == {"reasoning": "low"}
    assert selection["planner"]["dialect"] == "openai"
    assert os.environ.get("TEXT_MODEL_PROVIDER", "") == selection["text"]["provider"]

# ── per-model parameter surfaces (the MVP-1 repair) ──────────────────────────


def test_the_catalogue_carries_the_spec_parameters():
    assert set(parameters.PARAMETER_CATALOG) == {
        "reasoning", "temperature", "stream", "max_tokens", "top_p", "seed", "stop",
        "frequency_penalty", "presence_penalty",
    }
    for name, definition in parameters.PARAMETER_CATALOG.items():
        assert definition["type"] in {"enum", "number", "integer", "boolean", "array", "string"}, name
        assert "description" in definition
    assert parameters.PARAMETER_CATALOG["frequency_penalty"]["advanced"] is True
    assert parameters.PARAMETER_CATALOG["temperature"]["advanced"] is False


def test_the_dialect_decides_what_a_model_can_receive():
    openai_schema = parameters.schema_for_model("groq", "openai/gpt-oss-20b", capabilities={"reasoning": True})
    assert {"temperature", "top_p", "seed", "frequency_penalty", "stop"} <= set(openai_schema["parameters"])
    anthropic_schema = parameters.schema_for_model("anthropic", "claude-sonnet-4-5", capabilities={"reasoning": False})
    assert "seed" not in anthropic_schema["parameters"]
    assert "frequency_penalty" not in anthropic_schema["parameters"]
    assert {"temperature", "top_p", "max_tokens"} <= set(anthropic_schema["parameters"])


def test_reasoning_controls_only_appear_for_reasoning_models():
    plain = parameters.schema_for_model("groq", "meta-llama/llama-3.3-70b-versatile")
    assert "reasoning" not in plain["parameters"]
    thinker = parameters.schema_for_model("groq", "openai/gpt-oss-120b")
    assert "reasoning" in thinker["parameters"]
    assert thinker["simple"][0] == "reasoning"  # and it is a simple-mode control


def test_family_rules_offer_the_documented_reasoning_values():
    schema = parameters.schema_for_model("nvidia", "moonshotai/kimi-k3", capabilities={"reasoning": True})
    assert schema["parameters"]["reasoning"]["values"] == ["low", "high", "max"]
    assert schema["parameters"]["reasoning"]["labels"]["max"] == "max"
    generic = parameters.schema_for_model("nvidia", "z-ai/glm-5.3", capabilities={"reasoning": True})
    assert generic["parameters"]["reasoning"]["values"] == ["none", "low", "medium", "high"]


def test_probe_results_add_and_remove_parameters():
    schema = parameters.schema_for_model(
        "groq", "some/model", capabilities={"reasoning": False}, probed={"seed": False, "top_p": True}
    )
    assert "seed" not in schema["parameters"]  # the probe saw it rejected
    assert "top_p" in schema["parameters"]


def test_schema_for_role_follows_the_selected_model(monkeypatch):
    monkeypatch.setattr(discovery, "REGISTRY_PATH", parameters.CONFIG_PATH.parent / "registry.json")
    registry = {
        "fetchedAt": time.time(),
        "providers": {
            "groq": {
                "ok": True,
                "models": [{
                    "id": "openai/gpt-oss-20b",
                    "provider": "groq",
                    "capabilities": {"reasoning": True},
                    "probedParams": {"seed": False},
                }],
            }
        },
    }
    monkeypatch.setattr(discovery, "_load_registry", lambda: registry)
    parameters.apply_model("policy", "groq", "openai/gpt-oss-20b")
    schema = parameters.schema_for_role("policy")
    assert schema["provider"] == "groq" and schema["model"] == "openai/gpt-oss-20b"
    assert "reasoning" in schema["parameters"] and "seed" not in schema["parameters"]


def test_schema_for_role_without_a_model_is_the_full_catalogue(monkeypatch):
    monkeypatch.setattr(discovery, "_load_registry", lambda: None)
    schema = parameters.schema_for_role("policy")
    assert schema["fallback"] is True
    assert set(schema["parameters"]) == set(parameters.PARAMETER_CATALOG)


def test_apply_params_rejects_what_the_model_cannot_accept(monkeypatch):
    registry = {
        "fetchedAt": time.time(),
        "providers": {"groq": {"ok": True, "models": [
            {"id": "meta-llama/llama-3.3-70b-versatile", "provider": "groq",
             "capabilities": {"reasoning": False}, "probedParams": {"seed": False}},
        ]}},
    }
    monkeypatch.setattr(discovery, "_load_registry", lambda: registry)
    parameters.apply_model("policy", "groq", "meta-llama/llama-3.3-70b-versatile")
    with pytest.raises(ValueError, match="not supported by"):
        parameters.apply_params("policy", {"reasoning": "high"})
    with pytest.raises(ValueError, match="not supported by"):
        parameters.apply_params("policy", {"seed": 7})
    applied = parameters.apply_params("policy", {"temperature": 0.3, "top_p": 0.9})
    assert applied == {"temperature": 0.3, "top_p": 0.9}


def test_new_parameter_types_round_trip_through_the_environment(monkeypatch):
    import os

    registry = {
        "fetchedAt": time.time(),
        "providers": {"groq": {"ok": True, "models": [
            {"id": "openai/gpt-oss-20b", "provider": "groq", "capabilities": {"reasoning": True}},
        ]}},
    }
    monkeypatch.setattr(discovery, "_load_registry", lambda: registry)
    parameters.apply_model("policy", "groq", "openai/gpt-oss-20b")
    parameters.apply_params("policy", {
        "stream": False, "max_tokens": 2048, "seed": 11, "stop": ["END", "STOP"], "top_p": 0.8,
    })
    assert os.environ["POLICY_STREAM"] == "false"
    assert os.environ["POLICY_MAX_TOKENS"] == "2048"
    assert os.environ["POLICY_SEED"] == "11"
    assert os.environ["POLICY_STOP"] == '["END", "STOP"]'
    selection = parameters.current_selection()
    assert selection["policy"]["params"]["stop"] == '["END", "STOP"]'
    parameters.apply_saved_config()  # a restart must restore the same values
    assert os.environ["POLICY_TOP_P"] == "0.8"


def test_prune_params_drops_what_the_new_model_lacks(monkeypatch):
    import os

    full = {"fetchedAt": time.time(), "providers": {"groq": {"ok": True, "models": [
        {"id": "openai/gpt-oss-20b", "provider": "groq", "capabilities": {"reasoning": True}},
    ]}}}
    lean = {"fetchedAt": time.time(), "providers": {"groq": {"ok": True, "models": [
        {"id": "meta-llama/llama-3.3-70b-versatile", "provider": "groq", "capabilities": {"reasoning": False}},
    ]}}}
    monkeypatch.setattr(discovery, "_load_registry", lambda: full)
    parameters.apply_model("policy", "groq", "openai/gpt-oss-20b")
    parameters.apply_params("policy", {"reasoning": "high", "temperature": 0.2})
    assert os.environ["POLICY_REASONING"] == "high"
    monkeypatch.setattr(discovery, "_load_registry", lambda: lean)
    parameters.apply_model("policy", "groq", "meta-llama/llama-3.3-70b-versatile")
    removed = parameters.prune_params("policy")
    assert removed == {"reasoning": "high"}
    assert "POLICY_REASONING" not in os.environ
    assert os.environ["POLICY_TEMPERATURE"] == "0.2"  # still valid for the new model
    assert parameters.load_config()["params"]["policy"] == {"temperature": 0.2}


def test_presets_skip_parameters_the_model_lacks(monkeypatch):
    registry = {
        "fetchedAt": time.time(),
        "providers": {"groq": {"ok": True, "models": [
            {"id": "meta-llama/llama-3.3-70b-versatile", "provider": "groq", "capabilities": {"reasoning": False}},
        ]}},
    }
    monkeypatch.setattr(discovery, "_load_registry", lambda: registry)
    for role in ("planner", "policy", "text"):
        parameters.apply_model(role, "groq", "meta-llama/llama-3.3-70b-versatile")
    applied = parameters.apply_preset("deep")
    assert applied["planner"] == {}  # no reasoning control on this model: nothing applied, no crash
    assert applied["policy"] == {}


def test_sidebar_schema_offers_a_surface_per_role(monkeypatch):
    monkeypatch.setattr(discovery, "_load_registry", lambda: None)
    schema = parameters.sidebar_schema()
    assert [role["key"] for role in schema["roles"]] == ["planner", "policy", "text"]
    for role in ("planner", "policy", "text"):
        assert "parameters" in schema["modelSchemas"][role]
        assert isinstance(schema["modelSchemas"][role]["simple"], list)
        assert isinstance(schema["modelSchemas"][role]["advanced"], list)
