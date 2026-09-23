"""The 241-mission routing battery must stay well-formed, and the shipped router must ace it.

These are contracts on data, not on prose: if someone adds a mission the router
misroutes, this fails and points at the exact case. Fix the keyword layer or the
case — never the assertion.
"""

import json

from jev_ultrafast import orchestrator
from scripts.routing_cases import (
    ADVERSARIAL,
    BROWSER_CORE,
    CORE_PER_LANGUAGE,
    LANGUAGES,
    ORCHESTRATED_CORE,
    ROUTING_CASES,
    load_extra_cases,
    summary,
)


def test_battery_composition_is_the_documented_one():
    counts = summary()
    assert counts["total"] == 241
    assert counts["core"] == 216
    assert counts["core_browser"] == 108
    assert counts["core_orchestrated"] == 108
    assert counts["adversarial"] == 25
    assert len(ROUTING_CASES) == len(ADVERSARIAL) + len(BROWSER_CORE) + len(ORCHESTRATED_CORE)


def test_every_language_has_the_same_number_of_core_missions():
    """Per-language accuracy is only comparable when every language carries the same load."""
    for language in LANGUAGES:
        browser = [case for case in BROWSER_CORE if case[0] == language]
        orchestrated = [case for case in ORCHESTRATED_CORE if case[0] == language]
        assert len(browser) == CORE_PER_LANGUAGE // 2, f"{language}: {len(browser)} browser missions"
        assert len(orchestrated) == CORE_PER_LANGUAGE // 2, f"{language}: {len(orchestrated)} orchestrated"
    assert len(LANGUAGES) * CORE_PER_LANGUAGE == len(BROWSER_CORE) + len(ORCHESTRATED_CORE)


def test_cases_are_labelled_uniquely_and_plausibly():
    ids = [case["id"] for case in ROUTING_CASES]
    missions = [case["mission"].strip().lower() for case in ROUTING_CASES]
    assert len(set(ids)) == len(ids)
    assert len(set(missions)) == len(missions), "a mission is listed twice"
    for case in ROUTING_CASES:
        assert case["expected"] in {"browser", "orchestrated"}
        assert case["lang"], case
        assert len(case["mission"].strip()) >= 12, f"mission too short to be realistic: {case['mission']!r}"
        assert case["kind"] in {"core", "mixed_intent", "long", "bilingual", "telegraphic", "typo"}


def test_adversarial_kinds_are_all_present():
    kinds = {case["kind"] for case in ROUTING_CASES if case["kind"] != "core"}
    assert kinds == {"mixed_intent", "long", "bilingual", "telegraphic", "typo"}
    mixed = [case for case in ROUTING_CASES if case["kind"] == "mixed_intent"]
    assert all(case["expected"] == "orchestrated" for case in mixed), (
        "mixed intent must follow the safe direction: any tool need routes to the tool loop"
    )


def test_shipped_keyword_router_routes_the_whole_battery_without_dangerous_confusion():
    """The regression net for 0.4.0: a tool mission must never land in the browser loop."""
    dangerous, over_routed = [], []
    for case in ROUTING_CASES:
        matched = orchestrator.orchestrated_keyword_match(case["mission"])
        predicted = "orchestrated" if matched else "browser"
        if predicted != case["expected"]:
            (dangerous if case["expected"] == "orchestrated" else over_routed).append(case)
    assert not dangerous, f"tool missions sent to the browser loop: {[c['mission'] for c in dangerous]}"
    assert not over_routed, f"page missions sent to the tool loop: {[c['mission'] for c in over_routed]}"


def test_keyword_matching_is_word_anchored_not_substring():
    """The bug the battery found: 'inscription' contains 'script', 'iscrivimi' contains 'scrivi'."""
    assert orchestrator.orchestrated_keyword_match("Remplis le formulaire d'inscription") is False
    assert orchestrator.orchestrated_keyword_match("Iscrivimi alla newsletter") is False
    assert orchestrator.orchestrated_keyword_match("Edita mi profile y guarda los cambios") is False
    assert orchestrator.orchestrated_keyword_match("Abre la descripción del producto") is False
    # the prefix form still catches inflection
    assert orchestrator.orchestrated_keyword_match("Descarga el informe") is True
    assert orchestrator.orchestrated_keyword_match("Descargar todos los archivos") is True
    assert orchestrator.orchestrated_keyword_match("Crea un script de python") is True


def test_legacy_matcher_still_reproduces_the_old_behaviour_for_measurement():
    """The benchmark needs the 0.3.0 rule to report an honest before/after."""
    assert orchestrator.legacy_keyword_match("Remplis le formulaire d'inscription", ("script",)) is True
    assert orchestrator.orchestrated_keyword_match("Remplis le formulaire d'inscription") is False


def test_extra_cases_load_from_a_jsonl_fixture(tmp_path):
    fixture = tmp_path / "extra.jsonl"
    fixture.write_text(
        "\n".join([
            "# comments and blank lines are skipped",
            "",
            json.dumps({"lang": "de", "mission": "Analysiere die Datei", "expected": "orchestrated"}),
            json.dumps({"lang": "es", "mission": "Acepta las cookies", "expected": "browser", "kind": "extra"}),
        ]),
        encoding="utf-8",
    )
    extra = load_extra_cases(fixture)
    assert [case["expected"] for case in extra] == ["orchestrated", "browser"]
    assert extra[0]["kind"] == "extra"
    assert extra[0]["id"].startswith("x")


def test_extra_case_fixture_errors_are_reported_with_the_line_number(tmp_path):
    fixture = tmp_path / "broken.jsonl"
    fixture.write_text('{"lang": "es", "mission": "", "expected": "browser"}\n', encoding="utf-8")
    try:
        load_extra_cases(fixture)
    except ValueError as error:
        assert "broken.jsonl:1" in str(error)
    else:
        raise AssertionError("an unlabelled case must not load silently")

    fixture.write_text('{"lang": "es", "mission": "algo", "expected": "browser"}\nnot json\n', encoding="utf-8")
    try:
        load_extra_cases(fixture)
    except ValueError as error:
        assert "broken.jsonl:2" in str(error)
    else:
        raise AssertionError("invalid JSON must not load silently")
