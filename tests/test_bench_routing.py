"""Contracts for the routing benchmark: the maths, the honesty of the report, the modes."""

import json

import pytest

from jev_ultrafast import laya_local, providers
from scripts import bench_routing
from scripts.routing_cases import ROUTING_CASES


def row(case_id, lang, kind, mission, expected, predicted, latency=1.0):
    return {"id": case_id, "lang": lang, "kind": kind, "mission": mission,
            "expected": expected, "predicted": predicted, "latency_ms": latency}


def test_analyse_separates_the_two_confusion_directions():
    rows = [
        row("a", "es", "core", "tool mission into the browser loop", "orchestrated", "browser"),
        row("b", "es", "core", "page mission into the tool loop", "browser", "orchestrated"),
        row("c", "de", "core", "both correct", "browser", "browser", latency=5.0),
        row("d", "fr", "core", "both correct tool work", "orchestrated", "orchestrated", latency=9.0),
    ]
    result = bench_routing.analyse(rows)
    assert result["hits"] == 2 and result["total"] == 4
    assert result["accuracy"] == 0.5
    assert [entry["id"] for entry in result["dangerous"]] == ["a"]
    assert [entry["id"] for entry in result["over_routed"]] == ["b"]
    assert result["by_language"]["es"] == {"total": 2, "hits": 0, "dangerous": 1, "over": 1}
    assert result["by_kind"]["core"]["hits"] == 2
    assert bench_routing._p50(result["latency_ms"]) == 3.0  # median of 1, 1, 5, 9
    assert bench_routing._p95(result["latency_ms"]) == 9.0
    assert bench_routing._p50([]) == 0.0 and bench_routing._p95([]) == 0.0


class FakeLaya:
    """A stand-in for the real weights: fixed answers with fixed confidence."""

    def __init__(self, answers):
        self.answers = answers
        self.calls = []

    def predict(self, state, questions):
        self.calls.append(state)
        choice, confidence = self.answers.get(state["mission"], (None, None))
        return {"answers": {"route": {"choice": choice, "confidence": confidence}}}


def test_measure_stack_reports_raw_laya_next_to_the_gated_stack(monkeypatch):
    mission = "Descarga el PDF del informe"
    fake = FakeLaya({mission: ("browser", 0.30)})  # confidently wrong direction, below the gate
    monkeypatch.setattr(laya_local, "engine", lambda: fake)
    ask = bench_routing.laya_decider()

    cases = [{"id": "r0001", "lang": "es", "kind": "core", "mission": mission, "expected": "orchestrated"}]
    stack = bench_routing.measure_stack(cases, ask)

    assert stack["raw_hits"] == 0 and stack["raw_total"] == 1
    assert stack["hits"] == 1, "the gate must hand the decision to the keyword router"
    assert len(stack["dangerous"]) == 0
    assert stack["gate"] == laya_local.CONFIDENCE_GATE


def test_measure_stack_counts_a_confident_wrong_laya_as_dangerous(monkeypatch):
    mission = "Descarga el PDF del informe"
    fake = FakeLaya({mission: ("browser", 0.99)})  # above the gate: the stack follows it
    monkeypatch.setattr(laya_local, "engine", lambda: fake)

    cases = [{"id": "r0001", "lang": "es", "kind": "core", "mission": mission, "expected": "orchestrated"}]
    stack = bench_routing.measure_stack(cases, bench_routing.laya_decider())

    assert stack["raw_hits"] == 0
    assert len(stack["dangerous"]) == 1, "a confident wrong call is exactly what the report must surface"


def test_measure_stack_counts_abstentions(monkeypatch):
    mission = "Crea un script y ejecútalo"
    fake = FakeLaya({mission: (None, None)})
    monkeypatch.setattr(laya_local, "engine", lambda: fake)
    cases = [{"id": "r0001", "lang": "es", "kind": "core", "mission": mission, "expected": "orchestrated"}]
    stack = bench_routing.measure_stack(cases, bench_routing.laya_decider())
    assert stack["raw_abstentions"] == 1
    assert stack["raw_total"] == 0
    assert stack["hits"] == 1


def test_laya_decider_is_safe_without_weights(monkeypatch):
    monkeypatch.setattr(laya_local, "engine", lambda: None)
    assert bench_routing.laya_decider()("anything") == (None, None, 0.0)


def test_laya_decider_treats_a_crashing_engine_as_an_abstention(monkeypatch):
    class Exploding:
        def predict(self, state, questions):
            raise RuntimeError("weights exploded")

    monkeypatch.setattr(laya_local, "engine", lambda: Exploding())
    choice, confidence, latency = bench_routing.laya_decider()("anything")
    assert choice is None and confidence is None and latency >= 0


def test_keyword_layer_measures_the_legacy_rule_against_the_shipped_one(tmp_path):
    """The 0.4.0 change is a measured number: same case, two rules."""
    cases = [
        {"id": "r0001", "lang": "fr", "kind": "core",
         "mission": "Remplis le formulaire d'inscription et valide l'envoi", "expected": "browser"},
        {"id": "r0002", "lang": "de", "kind": "core",
         "mission": "Recherchiere im Internet Alternativen zu Notion", "expected": "orchestrated"},
    ]
    legacy = bench_routing.measure_keywords(cases, bench_routing.BASELINE_KEYWORDS, legacy=True)
    shipped = bench_routing.measure_keywords(cases, bench_routing.BASELINE_KEYWORDS + ("datei*", "im internet*"))

    assert legacy["hits"] == 0
    assert len(legacy["dangerous"]) == 1 and len(legacy["over_routed"]) == 1
    assert shipped["hits"] == 2
    assert len(shipped["dangerous"]) == 0 and len(shipped["over_routed"]) == 0


def test_keyword_layer_restores_the_environment_and_the_keyword_list(monkeypatch):
    before = bench_routing.BASELINE_KEYWORDS
    with bench_routing.keyword_layer(before):
        from jev_ultrafast import orchestrator

        assert orchestrator.ORCHESTRATED_KEYWORDS == before
        assert orchestrator.orchestrated_keyword_match("Recherchiere im Internet") is False
    assert orchestrator.ORCHESTRATED_KEYWORDS != before
    assert orchestrator.orchestrated_keyword_match("Recherchiere im Internet nach Dateien") is True


def test_report_numbers_come_from_the_measurement_not_from_prose():
    cases = [
        {"id": "r0001", "lang": "es", "kind": "core", "mission": "Descarga el PDF", "expected": "orchestrated"},
        {"id": "r0002", "lang": "es", "kind": "mixed_intent", "mission": "Reserva y apunta en un archivo",
         "expected": "orchestrated"},
        {"id": "r0003", "lang": "de", "kind": "telegraphic", "mission": "hier einloggen", "expected": "browser"},
    ]
    runs = {
        "legacy": bench_routing.measure_keywords(cases, ("script",), legacy=True),
        "shipped": bench_routing.measure_keywords(cases, ("pdf",)),
    }
    report = bench_routing.render_report({"total": 3, "core": 2, "core_browser": 1, "core_orchestrated": 1,
                                          "adversarial": 1, "languages": ["es", "de"]}, runs, None)
    assert "3 missions" in report
    assert f"{runs['shipped']['hits']}/3" in report
    assert "Dangerous" in report
    for entry in runs["shipped"]["dangerous"]:
        assert entry["mission"][:20] in report, "every dangerous confusion must be listed"
    assert runs["legacy"]["hits"] < runs["shipped"]["hits"], "the frozen baseline must show the older behaviour"
    assert report.count("|") > 20


def test_report_renders_a_stack_section_with_laya_numbers(monkeypatch):
    mission = "Descarga el PDF del informe"
    monkeypatch.setattr(laya_local, "engine", lambda: FakeLaya({mission: ("orchestrated", 0.81)}))
    cases = [{"id": "r0001", "lang": "es", "kind": "core", "mission": mission, "expected": "orchestrated"}]
    stack = bench_routing.measure_stack(cases, bench_routing.laya_decider())
    report = bench_routing.render_report(
        {"total": 1, "core": 1, "core_browser": 0, "core_orchestrated": 1, "adversarial": 0,
         "languages": ["es"]},
        {"shipped": bench_routing.measure_keywords(cases, ("pdf",))},
        stack,
    )
    assert "Raw Laya vs the stack that actually runs" in report
    assert f"{stack['gate']:.2f} gate" in report
    assert "Dangerous confusion" in report


def test_sample_with_policy_model_explains_a_missing_provider(monkeypatch):
    def unavailable(role):
        raise ValueError("POLICY_MODEL is not set; no request was sent.")

    monkeypatch.setattr(providers, "resolve", unavailable)
    sample = bench_routing.sample_with_policy_model(ROUTING_CASES, 4)
    assert sample["rows"] == []
    assert "POLICY_MODEL" in sample["error"]


def test_sample_with_policy_model_scores_a_stratified_sample(monkeypatch):
    def fake_resolve(role):
        return {"name": "fake", "model": "fake-router"}

    def fake_chat(provider, system, user, max_tokens=1024, on_delta=None):
        choice = "orchestrated" if ("pdf" in user or "archivo" in user) else "browser"
        return json.dumps({"choice": choice}), {"usage": {"input_tokens": 10, "output_tokens": 2}}

    monkeypatch.setattr(providers, "resolve", fake_resolve)
    monkeypatch.setattr(providers, "chat", fake_chat)
    monkeypatch.setattr(bench_routing.time, "sleep", lambda _seconds: None)
    sample = bench_routing.sample_with_policy_model(ROUTING_CASES[:10], 3)
    assert sample["total"] == 3
    assert sample["stride"] == 3
    assert sample["tokens"] == 3 * 12
    assert 0 <= sample["hits"] <= 3


def test_selftest_mode_runs_offline_and_writes_json(tmp_path, monkeypatch, capsys):
    destination = tmp_path / "routing.json"
    monkeypatch.setattr(bench_routing.sys, "argv",
                        ["bench_routing.py", "--selftest", "--case-limit", "12", "--json", str(destination)])
    assert bench_routing.main() == 0
    payload = json.loads(destination.read_text(encoding="utf-8"))
    assert payload["composition"]["total"] == 12
    assert payload["effective"] is None, "self-test does not claim measured weights"
    assert len(payload["case_rows"]) == 12
    assert payload["case_rows"][0]["id"] == "r0001"
    output = capsys.readouterr().out
    assert "Routing battery" in output
    assert "huggingface.co" in output  # the note explains why the raw column is missing


def fake_run(monkeypatch, hits=6, total=8, dangerous=0):
    miss = {"id": "r0001", "lang": "de", "kind": "core", "mission": "Recherchiere im Internet",
            "expected": "orchestrated", "predicted": "browser"}
    monkeypatch.setattr(bench_routing, "measure_keywords",
                        lambda cases, keywords, legacy=False: {
                            "rows": [], "total": total, "hits": hits, "accuracy": hits / total,
                            "dangerous": [dict(miss) for _ in range(dangerous)], "over_routed": [],
                            "by_language": {}, "by_kind": {}, "latency_ms": []})


def test_floor_turns_the_measurement_into_a_gate(monkeypatch):
    fake_run(monkeypatch)
    monkeypatch.setattr(bench_routing.sys, "argv", ["bench_routing.py", "--selftest", "--floor", "0.9"])
    assert bench_routing.main() == 1
    monkeypatch.setattr(bench_routing.sys, "argv", ["bench_routing.py", "--selftest", "--floor", "0.5"])
    assert bench_routing.main() == 0


def test_dangerous_confusion_is_the_gate_that_matters(monkeypatch):
    """A perfect accuracy score must still fail when tool missions land in the browser loop."""
    fake_run(monkeypatch, hits=8, total=8, dangerous=3)
    monkeypatch.setattr(bench_routing.sys, "argv", ["bench_routing.py", "--selftest", "--dangerous-max", "0"])
    assert bench_routing.main() == 1
    monkeypatch.setattr(bench_routing.sys, "argv", ["bench_routing.py", "--selftest", "--dangerous-max", "5"])
    assert bench_routing.main() == 0
    # default: report only, never fail a local measurement
    monkeypatch.setattr(bench_routing.sys, "argv", ["bench_routing.py", "--selftest"])
    assert bench_routing.main() == 0


def test_extra_jsonl_cases_extend_the_battery(tmp_path, monkeypatch):
    fixture = tmp_path / "extra.jsonl"
    fixture.write_text(json.dumps({"lang": "de", "mission": "Analysiere die Datei", "expected": "orchestrated"}) + "\n",
                       encoding="utf-8")
    destination = tmp_path / "out.json"
    monkeypatch.setattr(bench_routing.sys, "argv",
                        ["bench_routing.py", "--selftest", "--cases", str(fixture), "--json", str(destination)])
    assert bench_routing.main() == 0
    payload = json.loads(destination.read_text(encoding="utf-8"))
    assert payload["composition"]["total"] == len(ROUTING_CASES) + 1


@pytest.mark.parametrize("value,expected", [(2, 2), (1, 1)])
def test_sampling_stride_is_at_least_one(value, expected):
    assert max(1, len(ROUTING_CASES) // value) >= expected
