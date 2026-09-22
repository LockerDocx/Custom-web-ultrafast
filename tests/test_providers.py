"""Tests for multi-provider LLM support (OpenRouter, OmniRoute, NVIDIA NIM, Anthropic, OpenAI)."""

import json
from unittest.mock import Mock

import pytest

from jev_ultrafast import providers
from jev_ultrafast.model import action_space, choose


def dummy_page():
    return {
        "url": "https://flights.example.com",
        "title": "Search Flights",
        "text": "Cheap flights worldwide",
        "scroll": {"y": 0, "height": 1000},
        "actions": [
            {"id": "e1", "kind": "fill", "label": "Origin", "role": "textbox", "value": "Zurich", "node": 1},
            {"id": "e2", "kind": "fill", "label": "Destination", "role": "textbox", "value": "", "node": 2},
            {"id": "e3", "kind": "click", "label": "Search", "role": "button", "value": "", "node": 3},
            {
                "id": "e4",
                "kind": "select",
                "label": "Cabin",
                "role": "combobox",
                "value": "econ",
                "current_value": "Economy",
                "node": 4,
            },
            {"id": "scroll_down", "kind": "scroll", "label": "Scroll down", "delta": 560},
            {"id": "wait", "kind": "wait", "label": "Wait"},
        ],
    }


def test_provider_detection(monkeypatch):
    monkeypatch.delenv("LLM_PROVIDER", raising=False)
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    monkeypatch.delenv("OMNIROUTE_API_KEY", raising=False)
    monkeypatch.delenv("NVIDIA_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("TYPESAFE_API_KEY", raising=False)
    monkeypatch.delenv("LLM_API_KEY", raising=False)

    monkeypatch.setenv("OPENAI_API_KEY", "sk-openai-test")
    assert providers.detect_provider() == "openai"

    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")
    assert providers.detect_provider() == "anthropic"

    monkeypatch.setenv("NVIDIA_API_KEY", "nv-test")
    assert providers.detect_provider() == "nvidia"

    monkeypatch.setenv("OMNIROUTE_API_KEY", "omni-test")
    assert providers.detect_provider() == "omniroute"

    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-test")
    assert providers.detect_provider() == "openrouter"

    monkeypatch.setenv("LLM_PROVIDER", "nvidia")
    assert providers.detect_provider() == "nvidia"


def test_provider_config_custom_override(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "omniroute")
    monkeypatch.setenv("OMNIROUTE_BASE_URL", "http://192.168.1.50:20128/v1")
    monkeypatch.setenv("OMNIROUTE_MODEL", "custom-fast-model")
    monkeypatch.setenv("OMNIROUTE_API_KEY", "my-gateway-key")

    cfg = providers.get_provider_config()
    assert cfg["provider"] == "omniroute"
    assert cfg["base_url"] == "http://192.168.1.50:20128/v1"
    assert cfg["model"] == "custom-fast-model"
    assert cfg["api_key"] == "my-gateway-key"
    assert cfg["api_type"] == "openai"


@pytest.mark.parametrize(
    "raw,expected_op,expected_target,expected_text",
    [
        ('{"thought": "search", "operation": "CLICK", "target": "3"}', "CLICK", "3", None),
        (
            '```json\n{"thought": "type", "operation": "TYPE_TEXT", "target": "2", "text": "London"}\n```',
            "TYPE_TEXT",
            "2",
            "London",
        ),
        ('Here is the choice:\n{"thought": "done", "operation": "DONE"}\nHope this helps!', "DONE", None, None),
        ('{"thought": "scroll", "operation": "SCROLL_DOWN"}', "SCROLL_DOWN", None, None),
    ],
)
def test_extract_json_and_resolve_action(raw, expected_op, expected_target, expected_text):
    page = dummy_page()
    elements, targets, controls = action_space(page["actions"])
    parsed = providers.extract_json(raw)
    choice, op, target, text = providers.resolve_action_choice(parsed, targets, controls, page["actions"])

    assert op == expected_op
    assert target == expected_target
    assert text == expected_text
    if expected_op == "CLICK":
        assert choice == "e3"
    elif expected_op == "TYPE_TEXT":
        assert choice == "e2"
    elif expected_op == "DONE":
        assert choice == "DONE"
    elif expected_op == "SCROLL_DOWN":
        assert choice == "scroll_down"


def test_choose_llm_openai_compatible(monkeypatch):
    page = dummy_page()
    llm_response = {
        "choices": [
            {
                "message": {
                    "content": json.dumps({
                        "thought": "Enter destination London",
                        "operation": "TYPE_TEXT",
                        "target": "2",
                        "text": "London",
                    })
                }
            }
        ],
        "usage": {"total_tokens": 120},
    }

    mock_post = Mock(return_value=(llm_response, 180))
    monkeypatch.setattr(providers, "post_openai_compatible", mock_post)

    cfg = {
        "provider": "openrouter",
        "api_type": "openai",
        "base_url": "https://openrouter.ai/api/v1",
        "api_key": "test-key",
        "model": "deepseek/deepseek-chat",
    }

    decision = providers.choose_llm(page, "Fly to London", [], provider_config=cfg)

    assert decision["choice"] == "e2"
    assert decision["operation"] == "TYPE_TEXT"
    assert decision["target"] == "2"
    assert decision["text"] == "London"
    assert decision["thought"] == "Enter destination London"
    assert decision["confidence"] == 1.0
    assert decision["latency_ms"] == 180
    assert "openrouter" in decision["model"]
    assert mock_post.call_count == 1


def test_choose_llm_anthropic(monkeypatch):
    page = dummy_page()
    llm_response = {
        "content": [
            {
                "type": "text",
                "text": json.dumps({
                    "thought": "Click search button",
                    "operation": "CLICK",
                    "target": "3",
                }),
            }
        ],
        "usage": {"input_tokens": 80, "output_tokens": 25},
    }

    mock_post = Mock(return_value=(llm_response, 210))
    monkeypatch.setattr(providers, "post_anthropic", mock_post)

    cfg = {
        "provider": "anthropic",
        "api_type": "anthropic",
        "base_url": "https://api.anthropic.com/v1",
        "api_key": "sk-ant-test",
        "model": "claude-3-5-haiku-20241022",
    }

    decision = providers.choose_llm(page, "Click search", [], provider_config=cfg)

    assert decision["choice"] == "e3"
    assert decision["operation"] == "CLICK"
    assert decision["target"] == "3"
    assert decision["thought"] == "Click search button"
    assert decision["latency_ms"] == 210
    assert mock_post.call_count == 1


def test_model_choose_dispatches_to_configured_provider(monkeypatch):
    page = dummy_page()
    monkeypatch.setenv("LLM_PROVIDER", "nvidia")
    monkeypatch.setenv("NVIDIA_API_KEY", "nv-test-key")

    mock_choose_llm = Mock(return_value={
        "choice": "e3",
        "operation": "CLICK",
        "target": "3",
        "confidence": 1.0,
        "probabilities": {"e3": 1.0},
        "latency_ms": 150,
        "model": "nvidia/meta/llama-3.1-70b-instruct",
    })
    monkeypatch.setattr(providers, "choose_llm", mock_choose_llm)

    res = choose(page, "Test goal", [])
    assert res["choice"] == "e3"
    assert mock_choose_llm.call_count == 1
