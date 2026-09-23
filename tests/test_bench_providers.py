"""Contracts for the provider bench: real usage capture, honest failures, honest costs."""

import json

import pytest

from jev_ultrafast import providers
from scripts import bench_providers


def fake_chat_factory(tokens_in=100, tokens_out=20, content='{"choice": "browser"}'):
    def fake_chat(provider, system, user, max_tokens=1024, on_delta=None):
        return content, {"model": provider.get("model", "fake"), "usage": {"prompt_tokens": tokens_in,
                                                                         "completion_tokens": tokens_out}}
    return fake_chat


def test_percentiles_handle_small_and_empty_samples():
    assert bench_providers._percentile([], 0.95) == 0.0
    assert bench_providers._percentile([7.0], 0.5) == 7.0
    assert bench_providers._percentile([1.0, 2.0, 3.0, 4.0, 5.0], 0.5) == 3.0
    assert bench_providers._percentile([1.0, 2.0, 3.0, 4.0, 5.0], 0.95) == 5.0


def test_recording_chat_captures_usage_and_restores_the_seam(monkeypatch):
    monkeypatch.setattr(providers, "chat", fake_chat_factory())
    original = providers.chat
    with bench_providers.recording_chat() as seen:
        providers.chat({"name": "fake", "model": "m"}, "s", "u")
        providers.chat({"name": "fake", "model": "m"}, "s", "u")
    assert seen["calls"] == 2
    assert seen["models"] == ["m", "m"]
    assert providers.chat is original, "the seam must be restored even after a failure"


def test_recording_chat_restores_the_seam_after_an_exception(monkeypatch):
    def exploding(provider, system, user, max_tokens=1024, on_delta=None):
        raise RuntimeError("provider down")

    monkeypatch.setattr(providers, "chat", exploding)
    worked = providers.chat
    with pytest.raises(RuntimeError):
        with bench_providers.recording_chat():
            providers.chat({"name": "fake", "model": "m"}, "s", "u")
    assert providers.chat is worked


def test_measure_operation_records_latency_and_tokens(monkeypatch):
    monkeypatch.setattr(providers, "chat", fake_chat_factory(tokens_in=50, tokens_out=5))

    def action():
        return providers.chat({"name": "fake", "model": "m"}, "s", "u")

    operation = {"role": "policy", "action": action}
    entry = bench_providers.measure_operation("route", operation, samples=2, pacing=0.0)
    assert entry["ok"] == 2
    assert len(entry["latency_ms"]) == 2
    assert entry["tokens_in"] == 100 and entry["tokens_out"] == 10
    assert entry["error"] is None


def test_measure_operation_records_failures_without_hiding_them(monkeypatch):
    def failing():
        raise RuntimeError("Model provider returned HTTP 403: bad key")

    entry = bench_providers.measure_operation("choose", {"role": "policy", "action": failing}, samples=3, pacing=0.0)
    assert entry["ok"] == 0
    assert entry["latency_ms"] == []
    assert "HTTP 403" in entry["error"]
    report = bench_providers.render_report([entry], {})
    assert "failed" in report and "403" in report


def test_build_operation_rejects_unknown_names():
    with pytest.raises(ValueError):
        bench_providers.build_operation("teleport")


def test_build_operation_reports_a_missing_role(monkeypatch):
    def unavailable(role):
        raise ValueError("POLICY_MODEL is not set")

    monkeypatch.setattr(providers, "resolve", unavailable)
    with pytest.raises(ValueError):
        bench_providers.build_operation("choose")


def test_operations_cover_the_real_code_paths():
    """route/choose/plan/text must be the product's own calls, not rewritten prompts."""
    import inspect

    source = inspect.getsource(bench_providers.build_operation)
    assert "model.choose(" in source
    assert "model.plan_steps(" in source
    assert "model.field_text(" in source
    assert "model.field_context(" in source


def test_prices_validation_and_lookup(tmp_path):
    path = tmp_path / "prices.json"
    path.write_text(json.dumps({
        "groq:openai/gpt-oss-20b": {"input": 0.15, "output": 0.75},
        "cheap-model": {"input": 1, "output": 2},
    }), encoding="utf-8")
    prices = bench_providers.load_prices(path)
    assert prices["groq:openai/gpt-oss-20b"]["input"] == 0.15
    assert bench_providers.price_for(prices, "groq:openai/gpt-oss-20b")["output"] == 0.75
    assert bench_providers.price_for(prices, "local:cheap-model")["input"] == 1.0  # bare-model fallback
    assert bench_providers.price_for(prices, "unknown:model") is None

    path.write_text(json.dumps({"bad": {"input": 1}}), encoding="utf-8")
    with pytest.raises(ValueError):
        bench_providers.load_prices(path)
    assert bench_providers.load_prices("") == {}


def test_cost_projection_uses_measured_tokens():
    entry = {"ok": 2, "tokens_in": 1000, "tokens_out": 500, "latency_ms": [1.0, 2.0], "samples": 2}
    price = {"input": 1.0, "output": 2.0}  # USD per million tokens
    # per 1000 calls: 2 measured calls → scale 500
    assert bench_providers.cost_usd(entry, price, 1000) == pytest.approx((500_000 / 1e6) * 1.0 + (250_000 / 1e6) * 2.0)
    assert bench_providers.cost_usd(entry, None, 1000) is None
    assert bench_providers.cost_usd({**entry, "ok": 0}, price, 1000) is None


def test_report_omits_costs_without_prices_and_labels_missing_prices():
    entry = {"operation": "choose", "role": "policy", "samples": 2, "ok": 2, "latency_ms": [100.0, 300.0],
             "tokens_in": 2000, "tokens_out": 400, "error": None, "model": "groq:openai/gpt-oss-20b"}
    without = bench_providers.render_report([entry], {})
    assert "Costs omitted" in without
    assert "300 ms" in without or "max" in without

    with_prices = bench_providers.render_report([entry], {"groq:openai/gpt-oss-20b": {"input": 0.15, "output": 0.75}})
    assert "Projected cost per 1,000 calls" in with_prices
    assert "$" in with_prices
    unpriced = bench_providers.render_report([entry], {"other:model": {"input": 1, "output": 1}})
    assert "no price supplied" in unpriced


def test_main_reports_configured_and_skipped_operations(monkeypatch, tmp_path, capsys):
    calls = {"count": 0}

    def fake_action():
        calls["count"] += 1
        return "browser"

    def fake_build(name):
        if name == "missing":
            raise ValueError("TEXT_MODEL is not set")
        return {"role": "policy", "action": fake_action}

    monkeypatch.setattr(bench_providers, "build_operation", fake_build)
    monkeypatch.setattr(bench_providers, "recording_chat", lambda: contextlib_nullcontext())
    destination = tmp_path / "providers.json"
    monkeypatch.setattr(bench_providers.sys, "argv",
                        ["bench_providers.py", "--samples", "2", "--operations", "route,missing",
                         "--json", str(destination), "--pacing", "0"])
    assert bench_providers.main() == 0
    payload = json.loads(destination.read_text(encoding="utf-8"))
    assert [entry["operation"] for entry in payload["results"]] == ["route"]
    assert payload["skipped"][0]["operation"] == "missing"
    output = capsys.readouterr().out
    assert "run 1" not in output and "route" in output


def test_main_fails_when_nothing_completed(monkeypatch, capsys):
    def failing_action():
        raise RuntimeError("HTTP 500: provider down")

    monkeypatch.setattr(bench_providers, "build_operation",
                        lambda name: {"role": "policy", "action": failing_action})
    monkeypatch.setattr(bench_providers.sys, "argv",
                        ["bench_providers.py", "--samples", "1", "--operations", "route", "--pacing", "0"])
    assert bench_providers.main() == 1
    assert "No operation completed" in capsys.readouterr().out


class contextlib_nullcontext:
    """A no-op context manager that yields an empty usage record."""

    def __enter__(self):
        return {"usage": [], "calls": 0, "models": []}

    def __exit__(self, *_args):
        return False
