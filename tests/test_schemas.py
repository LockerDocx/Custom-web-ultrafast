"""Contracts for the per-model parameter schemas (MVP-1).

NVIDIA NIM's catalogue is a moving target: these tests pin the behaviour that
keeps a model change from breaking inference — the surface comes from family
rules plus live evidence, never from a hardcoded list.
"""

import json

import pytest

from jev_ultrafast import discovery, model, parameters, providers, schemas


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    monkeypatch.setattr(schemas, "RUNTIME_PATH", tmp_path / "runtime.json")
    monkeypatch.setattr(discovery, "REGISTRY_PATH", tmp_path / "registry.json")
    monkeypatch.setattr(parameters, "CONFIG_PATH", tmp_path / "config.json")
    for role in ("PLANNER", "POLICY", "TEXT_MODEL"):
        for suffix in ("PROVIDER", "MODEL", "API_KEY", "BASE_URL", "REASONING", "TEMPERATURE",
                       "TOP_P", "MAX_TOKENS", "SEED", "STOP", "STREAM",
                       "FREQUENCY_PENALTY", "PRESENCE_PENALTY", "JSON_MODE"):
            monkeypatch.delenv(f"{role}_{suffix}" if suffix else role, raising=False)
    monkeypatch.delenv("TEXT_MODEL", raising=False)
    yield


REASONING_CAPS = {"reasoning": True, "inferred": True}


def test_each_family_exposes_its_own_surface():
    """The spec's §5.1 table: two NVIDIA models, two different control sets."""
    kimi = schemas.schema_for("nvidia", "moonshotai/kimi-k3", REASONING_CAPS)
    glm = schemas.schema_for("nvidia", "z-ai/glm-5.3", REASONING_CAPS)
    assert kimi["schemaId"] == "kimi-v1" and glm["schemaId"] == "glm-v1"
    # Kimi's playground surface has no top_p or penalties; GLM's has both
    assert "top_p" not in kimi["parameters"] and "top_p" in glm["parameters"]
    assert "frequency_penalty" not in kimi["parameters"]
    assert {"stream", "max_tokens", "temperature", "seed"} <= set(glm["parameters"])
    # and the reasoning ladders differ
    assert kimi["parameters"]["reasoning"]["values"] == ["low", "high", "max"]
    assert glm["parameters"]["reasoning"]["values"] == ["none", "low", "medium", "high"]


def test_reasoning_reaches_the_wire_the_way_each_family_wants_it():
    def body(model_id, setting, provider="nvidia"):
        schema = schemas.schema_for(provider, model_id, REASONING_CAPS)
        return schemas.reasoning_body(setting, schema["reasoning"], provider)

    assert body("moonshotai/kimi-k3", "max") == {"reasoning_effort": "max"}
    assert body("z-ai/glm-5.3", "high") == {"chat_template_kwargs": {"thinking": True}}
    assert body("z-ai/glm-5.3", "none") == {"chat_template_kwargs": {"thinking": False}}
    assert body("nvidia/llama-3.3-nemotron-super-49b", "low") == {"chat_template_kwargs": {"thinking": True}}
    assert body("openai/gpt-oss-120b", "high") == {"reasoning_effort": "high"}
    # a preset asking for a level the family lacks snaps to the nearest one
    assert body("moonshotai/kimi-k3", "medium") == {"reasoning_effort": "high"}
    # DeepSeek-R1 always reasons: there is no control and nothing to send
    r1 = schemas.schema_for("nvidia", "deepseek-ai/deepseek-r1", REASONING_CAPS)
    assert "reasoning" not in r1["parameters"]


def test_models_without_reasoning_get_no_reasoning_control():
    plain = schemas.schema_for("nvidia", "meta/llama-3.1-8b-instruct", {"reasoning": False, "inferred": True})
    assert "reasoning" not in plain["parameters"]


def test_anthropic_and_gemini_surfaces_are_narrower():
    claude = schemas.schema_for("anthropic", "claude-sonnet-4", {}, dialect="anthropic")
    assert set(claude["parameters"]) == {"temperature", "max_tokens", "stream", "top_p", "stop"}
    gemini = schemas.schema_for("gemini", "gemini-3-pro", REASONING_CAPS)
    assert "frequency_penalty" not in gemini["parameters"] and "seed" not in gemini["parameters"]


def test_runtime_evidence_removes_and_marks_parameters():
    schemas.record_unsupported("nvidia", "z-ai/glm-5.3", "seed")
    schemas.record_verified("nvidia", "z-ai/glm-5.3", ["temperature", "top_p"])
    schema = schemas.schema_for("nvidia", "z-ai/glm-5.3", REASONING_CAPS)
    assert "seed" not in schema["parameters"]
    assert schema["parameters"]["temperature"]["verified"] is True
    assert schema["unsupported"] == ["seed"]
    # a later success re-instates it
    schemas.record_verified("nvidia", "z-ai/glm-5.3", ["seed"])
    assert "seed" in schemas.schema_for("nvidia", "z-ai/glm-5.3", REASONING_CAPS)["parameters"]


def test_values_are_coerced_and_bounded():
    assert schemas.coerce("temperature", "0.35") == 0.35
    assert schemas.coerce("max_tokens", "512") == 512
    assert schemas.coerce("stream", "on") is True
    assert schemas.coerce("stop", "END, ###") == ["END", "###"]
    assert schemas.coerce("temperature", "") is None
    with pytest.raises(ValueError, match="between 0 and 1"):
        schemas.coerce("top_p", 4)
    with pytest.raises(ValueError, match="whole number"):
        schemas.coerce("seed", 1.5)
    with pytest.raises(ValueError, match="at most 4"):
        schemas.coerce("stop", "a,b,c,d,e")


def test_to_body_only_emits_supported_fields():
    schema = schemas.schema_for("nvidia", "z-ai/glm-5.3", REASONING_CAPS)
    body = schemas.to_body(
        {"temperature": 0.2, "top_p": 0.9, "stop": ["X"], "seed": 7, "reasoning": "high", "vibes": 1},
        schema,
    )
    assert body == {
        "temperature": 0.2,
        "top_p": 0.9,
        "stop": ["X"],
        "seed": 7,
        "chat_template_kwargs": {"thinking": True},
    }
    assert schemas.to_body({"top_p": 0.9}, schemas.schema_for("nvidia", "moonshotai/kimi-k3", REASONING_CAPS)) == {}


def test_request_carries_the_model_specific_parameters(monkeypatch):
    monkeypatch.setenv("POLICY_PROVIDER", "nvidia")
    monkeypatch.setenv("NVIDIA_API_KEY", "nvapi-test")
    monkeypatch.setenv("POLICY_MODEL", "z-ai/glm-5.3")
    monkeypatch.setenv("POLICY_TEMPERATURE", "0.3")
    monkeypatch.setenv("POLICY_TOP_P", "0.8")
    monkeypatch.setenv("POLICY_STOP", "END,###")
    monkeypatch.setenv("POLICY_MAX_TOKENS", "256")
    monkeypatch.setenv("POLICY_REASONING", "high")
    provider = providers.resolve("policy")
    _, _, body = providers.build_request(provider, "s", "u", 1024)
    assert body["temperature"] == 0.3 and body["top_p"] == 0.8
    assert body["stop"] == ["END", "###"]
    assert body["chat_template_kwargs"] == {"thinking": True}
    assert body["max_tokens"] == 256  # the user's cap lowers the caller's budget
    # ... but never below the floor that keeps the JSON protocol working
    monkeypatch.setenv("POLICY_MAX_TOKENS", "1")
    _, _, body = providers.build_request(providers.resolve("policy"), "s", "u", 1024)
    assert body["max_tokens"] == providers.MIN_OUTPUT_TOKENS


def test_a_rejected_parameter_is_remembered_and_stops_being_sent(monkeypatch):
    monkeypatch.setenv("POLICY_PROVIDER", "nvidia")
    monkeypatch.setenv("NVIDIA_API_KEY", "nvapi-test")
    monkeypatch.setenv("POLICY_MODEL", "z-ai/glm-5.3")
    monkeypatch.setenv("POLICY_TOP_P", "0.8")
    monkeypatch.setenv("POLICY_SEED", "7")
    calls = []

    def fake_post(_url, _key, body, headers=None):
        calls.append(body)
        if "seed" in body:
            raise RuntimeError("HTTP 400: unsupported parameter: seed")
        return {"choices": [{"message": {"content": "ok"}}]}

    monkeypatch.setattr(model, "post_json", fake_post)
    providers.chat(providers.resolve("policy"), "s", "u")
    assert len(calls) == 2 and "seed" not in calls[1]
    evidence = schemas.runtime_evidence("nvidia", "z-ai/glm-5.3")
    assert evidence["unsupported"] == ["seed"] and "top_p" in evidence["verified"]
    # the next resolve no longer offers, or sends, the rejected parameter
    schema = providers.resolve("policy")["schema"]
    assert "seed" not in schema["parameters"]
    assert "seed" not in providers.resolve("policy")["params"]


def test_probe_reports_what_the_endpoint_accepts(monkeypatch):
    monkeypatch.setenv("NVIDIA_API_KEY", "nvapi-test")

    def fake_post(_url, _key, body, headers=None):
        if "frequency_penalty" in body:
            raise RuntimeError("HTTP 400: frequency_penalty is not supported")
        return {"choices": [{"message": {"content": "OK"}}]}

    monkeypatch.setattr(model, "post_json", fake_post)
    report = discovery.probe_model("nvidia", "z-ai/glm-5.3")
    assert report["schemaId"] == "glm-v1"
    assert "frequency_penalty" in report["unsupported"]
    assert "temperature" in report["verified"] and report["error"] is None


def test_registry_entries_carry_the_schema_and_endpoint(monkeypatch):
    monkeypatch.setenv("NVIDIA_API_KEY", "nvapi-test")

    class Response:
        status_code = 200
        is_error = False

        def json(self):
            return {"data": [{"id": "moonshotai/kimi-k3"}, {"id": "z-ai/glm-5.3"}]}

    monkeypatch.setattr(model, "CLIENT", type("C", (), {"get": lambda *a, **k: Response()})())
    models = discovery.fetch_models("nvidia")
    by_id = {entry["id"]: entry for entry in models}
    kimi = by_id["moonshotai/kimi-k3"]
    assert kimi["endpoint"] == "https://integrate.api.nvidia.com/v1"
    assert kimi["parametersSchema"] == "kimi-v1"
    assert "top_p" not in kimi["parameters"] and "reasoning" in kimi["parameters"]
    assert kimi["capabilities"]["reasoning"] is True
    assert kimi["discoveredAt"].endswith("Z") and kimi["source"].endswith("/models")


def test_role_schema_follows_the_selected_model_and_prunes_values():
    parameters.apply_model("planner", "nvidia", "z-ai/glm-5.3")
    parameters.apply_params("planner", {"top_p": 0.7, "temperature": 0.4})
    assert parameters.role_schema("planner")["schemaId"] == "glm-v1"
    removed = parameters.apply_model("planner", "nvidia", "moonshotai/kimi-k3")
    assert removed == ["top_p"]
    saved = json.loads(parameters.CONFIG_PATH.read_text())
    assert saved["params"]["planner"] == {"temperature": 0.4}


def test_presets_project_onto_what_the_model_supports():
    parameters.apply_model("policy", "nvidia", "moonshotai/kimi-k3")
    applied = parameters.apply_preset("coding")
    # "coding" asks for reasoning=medium + top_p, Kimi has neither as such
    assert applied["policy"] == {"reasoning": "high", "temperature": 0.2}
