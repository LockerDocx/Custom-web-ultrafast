"""The profile bench: it measures candidates, and it measures honest things.

Added with a question from a user — *"what if we limit the AI: use glm-5.3 flash without
reasoning?"*. That is a speed idea with a quality question attached, so the bench answers both,
and these tests keep it honest:

- every candidate profile must resolve to a provider/model/reasoning the app can really send,
- "thinking off" must reach the wire as thinking off (not as "no preference"),
- a missing key or a missing model is reported as such, never scored as a bad answer,
- the quality checks are objective: a valid plan, a routing decision against labelled missions,
  the exact value the goal supplied.

The measurement itself needs live keys and is not run here; what is tested is that the
measurement cannot lie about what it sent or about why it failed.
"""

import importlib.util
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location("bench_profiles", ROOT / "scripts" / "bench_profiles.py")
bench = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(bench)

from jev_ultrafast import providers  # noqa: E402
from jev_ultrafast.schemas import reasoning_body  # noqa: E402

KEY_VARS = (
    "NVIDIA_API_KEY", "NVIDIA_NIM_API_KEY", "GROQ_API_KEY", "DEEPSEEK_API_KEY",
    "PLANNER_PROVIDER", "PLANNER_MODEL", "PLANNER_REASONING",
    "POLICY_PROVIDER", "POLICY_MODEL", "POLICY_REASONING",
    "TEXT_MODEL_PROVIDER", "TEXT_MODEL", "TEXT_MODEL_REASONING",
)


@pytest.fixture
def env_of(monkeypatch):
    """A clean provider environment, so a profile is measured with nothing else set."""
    for name in KEY_VARS:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("NVIDIA_API_KEY", "nvapi_test")
    monkeypatch.setenv("GROQ_API_KEY", "gsk_test")
    return monkeypatch


def test_every_profile_says_what_it_would_send(env_of):
    """Each candidate resolves to a real provider, model and reasoning setting."""
    for name, profile in bench.PROFILES.items():
        for role, (provider_name, model, reasoning) in profile["roles"].items():
            assert provider_name in providers.PROVIDERS, f"{name}/{role}: unknown provider"
            assert model and "/" in model, f"{name}/{role}: the model id looks wrong"
            assert reasoning in {"default", "none", "low", "medium", "high", "max"}, f"{name}/{role}"


def test_thinking_off_really_means_off(env_of):
    """The point of the proposal: `none` must reach the endpoint as thinking disabled."""
    bench.apply_profile(bench.PROFILES["nvidia-flash-none"])
    wire = bench.describe_wire("policy")
    assert wire["model"] == "nvidia:z-ai/glm-5.3-flash"
    assert wire["reasoning"] == "none"
    body = reasoning_body("none", {"style": "template", "values": ["none", "low", "medium", "high"]})
    assert body == {"chat_template_kwargs": {"thinking": False}}, body
    # ...and that the setting is in the parameters the request will carry
    assert wire["params"].get("reasoning") == "none"


def test_a_profile_that_leaves_reasoning_alone_leaves_it_alone(env_of):
    """`default` must not smuggle a setting in: it is the app's own default, nothing else."""
    import os

    bench.apply_profile(bench.PROFILES["nvidia-current"])
    planner, policy = bench.describe_wire("planner"), bench.describe_wire("policy")
    assert planner["model"] == "nvidia:z-ai/glm-5.3"
    assert policy["model"] == "nvidia:openai/gpt-oss-20b"
    assert "PLANNER_REASONING" not in os.environ and "POLICY_REASONING" not in os.environ


def test_applying_a_profile_is_reversible(env_of):
    bench.apply_profile(bench.PROFILES["nvidia-hybrid"])
    assert providers.selection_for("policy") == ("nvidia", "z-ai/glm-5.3-flash")
    bench.apply_profile(bench.PROFILES["nvidia-current"])
    assert providers.selection_for("policy") == ("nvidia", "openai/gpt-oss-20b")
    assert providers.selection_for("planner") == ("nvidia", "z-ai/glm-5.3")


def test_a_missing_key_is_reported_not_scored(env_of):
    """Without the key the bench says so; it never turns that into a failed answer."""
    for name in ("NVIDIA_API_KEY", "NVIDIA_NIM_API_KEY"):
        env_of.delenv(name, raising=False)
    env_of.delenv("GROQ_API_KEY", raising=False)
    result = bench.call("policy", "system", "user", 16)
    assert result["ok"] is False
    # whether it reads "no key" or "no model yet" depends on how much is configured; both are a
    # configuration fact, never an answer from the model
    assert "no model yet" in result["error"] or "No API key" in result["error"], result["error"]
    assert result["content"] is None


def test_an_unavailable_catalogue_is_not_a_missing_model(env_of, monkeypatch):
    """A provider we cannot ask (no key, no network) must not be called a missing model."""
    for name in ("NVIDIA_API_KEY", "NVIDIA_NIM_API_KEY"):
        env_of.delenv(name, raising=False)
    ids, unavailable = bench.catalogue("nvidia")
    assert ids == [] and unavailable, "no key means no catalogue, and the report says why"
    monkeypatch.setattr(bench.discovery, "fetch_models", lambda _name: [{"id": "z-ai/glm-5.3"}])
    ids, unavailable = bench.catalogue("nvidia")
    assert unavailable is None and ids == ["z-ai/glm-5.3"]


def test_the_quality_checks_are_the_objective_ones(env_of):
    """The three checks a candidate must pass are the three the agent depends on."""
    assert bench.PLANNER_MISSIONS and all(len(mission) > 20 for mission in bench.PLANNER_MISSIONS)
    # the text cases carry the value the goal supplies, so "exact" has a meaning
    for goal, field, expected in bench.TEXT_CASES:
        assert field and expected and expected in goal, f"{expected!r} is not in {goal!r}"
    # the routing battery supplies ground truth, and the bench keeps the dangerous direction apart
    assert bench.ROUTING_CASES, "the routing battery is the quality measure for the executor"
    assert all(case["expected"] in {"browser", "orchestrated"} for case in bench.ROUTING_CASES)


def test_a_report_is_serialisable_and_says_what_it_sent(env_of, monkeypatch):
    """The whole report round-trips through JSON: it is what the workflow keeps as an artifact."""
    monkeypatch.setattr(
        bench, "call", lambda *_a, **_k: {"ok": True, "latency_ms": 10, "error": None,
                                          "content": json.dumps({"steps": ["a step"], "choice": "browser",
                                                                 "text": "4"}), "usage": {}}
    )
    monkeypatch.setattr(bench, "catalogue", lambda _name: (["z-ai/glm-5.3-flash"], None))
    args = type("A", (), {"plans": 1, "routing_sample": 1, "text_cases": 1})()
    report = bench.run_profile("nvidia-flash-none", bench.PROFILES["nvidia-flash-none"], args)
    text = json.dumps(report, ensure_ascii=False)
    assert "nvidia:z-ai/glm-5.3-flash" in text
    assert report["wire"]["policy"]["reasoning"] == "none"
    assert report["quality"]["policy"]["scored"] >= 1
    rendered = bench.render(report)
    assert rendered is report
