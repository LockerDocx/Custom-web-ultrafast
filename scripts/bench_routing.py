#!/usr/bin/env python3
"""Measure the routing decision at scale: raw Laya vs the stack that actually runs.

Every mission in the battery is routed TWICE:

1. **Raw Laya** — the open weights answer on their own, ignoring the confidence gate.
   This is the quality of the open decision engine as-is, and it is what the duel
   measured on 24 cases (42%).
2. **Effective stack** — exactly what the agent does at runtime: Laya decides when it
   is calibrated above the 0.75 gate, the keyword router handles every abstention
   (low confidence or no decision at all).

The headline metric is **dangerous confusion**: a mission that needs the tool loop
(search, files, documents, terminal) but is routed to the browser loop. That failure
cannot self-heal — the browser loop has no tool to accomplish it. The opposite
mistake (browser work sent to the tool loop) is slower but still completes, so it is
reported separately as *safe over-routing*.

Two keyword layers are measured side by side, because that is what 0.4.0 changes:
the frozen `baseline` list (Spanish/English only) and the `extended` list shipped in
`jev_ultrafast.orchestrator` (six languages).

Usage:
    python scripts/bench_routing.py --selftest           # offline: keyword layers only
    python scripts/bench_routing.py                      # + real Laya weights (needs a download)
    python scripts/bench_routing.py --sample 24          # + a sampled GPT policy-model cross-check
    python scripts/bench_routing.py --json artifacts/routing.json --cases extra.jsonl

Exit code is 0 for a measurement. Pass `--floor 0.85` to fail a build below that
effective accuracy.
"""

import argparse
import json
import os
import statistics
import sys
import time
from collections import defaultdict
from contextlib import contextmanager
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from scripts.routing_cases import ROUTING_CASES, load_extra_cases, summary  # noqa: E402

# The Spanish/English-only keyword list shipped before 0.4.0, frozen here so the
# effect of the multilingual extension is a measured number, not a claim.
BASELINE_KEYWORDS = (
    "pdf", "docx", "xlsx", "excel", "spreadsheet", "word document",
    "project", "script", "create a file", "write a file", "save", "download",
    "crea un", "crea el", "escribe", "descarga", "archivo",
    "run the test", "run tests", "install", "command", "terminal", "bash",
    "npm ", "pip ", "git init", "ejecuta", "instala",
    "research", "investigate", "find information about", "compare",
    "investiga", "busca información",
)

GPT_PACING_SECONDS = 2.2  # keep a free tier's rate limit comfortable
ROUTING_SYSTEM = (
    "You are a mission router for a browser agent. Reply with ONLY one JSON object: "
    '{"choice": "browser"} or {"choice": "orchestrated"}. '
    "'browser' = the mission is completed by interacting with the current web page "
    "(clicking, filling, navigating, booking on that site, reading what it shows). "
    "'orchestrated' = the mission needs searching the wider web, opening other sites, "
    "downloading a file, parsing or creating documents, or running commands and code. "
    "If any part of the mission needs those tools, answer 'orchestrated'."
)


def _p50(values):
    return statistics.median(values) if values else 0.0


def _p95(values):
    if not values:
        return 0.0
    ordered = sorted(values)
    index = min(len(ordered) - 1, int(round(0.95 * (len(ordered) - 1))))
    return ordered[index]


def _pct(hits, total):
    return f"{hits / total:.0%}" if total else "—"


@contextmanager
def keyword_layer(keywords, legacy=False):
    """Route through the real `orchestrator.route_task` with Laya off and a frozen keyword list.

    `legacy` also restores the 0.3.0 substring rule, so the baseline row measures the
    behaviour that shipped, not today's matcher wearing an old keyword list.
    """
    from jev_ultrafast import orchestrator

    previous_env = os.environ.get("JEV_LAYA")
    previous_keywords = orchestrator.ORCHESTRATED_KEYWORDS
    previous_match = orchestrator.orchestrated_keyword_match
    os.environ["JEV_LAYA"] = "off"
    orchestrator.ORCHESTRATED_KEYWORDS = tuple(keywords)
    if legacy:
        orchestrator.orchestrated_keyword_match = (
            lambda goal, _keywords=None, _list=tuple(keywords): orchestrator.legacy_keyword_match(goal, _list)
        )
    try:
        yield orchestrator.route_task
    finally:
        orchestrator.ORCHESTRATED_KEYWORDS = previous_keywords
        orchestrator.orchestrated_keyword_match = previous_match
        if previous_env is None:
            os.environ.pop("JEV_LAYA", None)
        else:
            os.environ["JEV_LAYA"] = previous_env


def measure_keywords(cases, keywords, legacy=False):
    """Run the battery through the keyword layer alone — no weights, no network."""
    with keyword_layer(keywords, legacy=legacy) as route:
        rows = []
        for case in cases:
            started = time.perf_counter()
            predicted = route(case["mission"])
            rows.append({
                "id": case["id"],
                "lang": case["lang"],
                "kind": case["kind"],
                "mission": case["mission"],
                "expected": case["expected"],
                "predicted": predicted,
                "latency_ms": round((time.perf_counter() - started) * 1000, 3),
            })
    return analyse(rows, predicted_key="predicted")


def measure_stack(cases, ask_laya):
    """Raw Laya next to the effective stack (Laya above the gate, keywords below it)."""
    from jev_ultrafast import laya_local, orchestrator

    rows = []
    for case in cases:
        raw_choice, confidence, raw_ms = ask_laya(case["mission"])
        started = time.perf_counter()
        effective = orchestrator.route_task(case["mission"])
        rows.append({
            "id": case["id"],
            "lang": case["lang"],
            "kind": case["kind"],
            "mission": case["mission"],
            "expected": case["expected"],
            "raw": raw_choice,
            "raw_confidence": confidence,
            "raw_ms": raw_ms,
            "predicted": effective,
            "latency_ms": round((time.perf_counter() - started) * 1000, 3),
        })
    result = analyse(rows, predicted_key="predicted")
    result["raw_hits"] = sum(1 for row in rows if row["raw"] == row["expected"])
    result["raw_total"] = sum(1 for row in rows if row["raw"] is not None)
    result["raw_abstentions"] = sum(1 for row in rows if row["raw"] is None)
    result["raw_ms"] = [row["raw_ms"] for row in rows if row["raw_ms"]]
    result["gate"] = laya_local.CONFIDENCE_GATE
    result["laya_status"] = laya_local.status()
    return result


def analyse(rows, predicted_key="predicted"):
    """Accuracy, both confusion directions, and the per-language / per-kind split."""
    total = len(rows)
    hits = sum(1 for row in rows if row[predicted_key] == row["expected"])
    dangerous = [row for row in rows if row["expected"] == "orchestrated" and row[predicted_key] != "orchestrated"]
    over_routed = [row for row in rows if row["expected"] == "browser" and row[predicted_key] == "orchestrated"]
    by_language = defaultdict(lambda: {"total": 0, "hits": 0, "dangerous": 0, "over": 0})
    by_kind = defaultdict(lambda: {"total": 0, "hits": 0, "dangerous": 0})
    for row in rows:
        bucket = by_language[row["lang"]]
        bucket["total"] += 1
        bucket["hits"] += row[predicted_key] == row["expected"]
        bucket["dangerous"] += row in dangerous
        bucket["over"] += row in over_routed
        kind = by_kind[row["kind"]]
        kind["total"] += 1
        kind["hits"] += row[predicted_key] == row["expected"]
        kind["dangerous"] += row in dangerous
    return {
        "rows": rows,
        "total": total,
        "hits": hits,
        "accuracy": hits / total if total else 0.0,
        "dangerous": dangerous,
        "over_routed": over_routed,
        "by_language": dict(sorted(by_language.items())),
        "by_kind": dict(sorted(by_kind.items())),
        "latency_ms": [row["latency_ms"] for row in rows if row.get("latency_ms")],
    }


def sample_with_policy_model(cases, sample_size):
    """Optional cross-check: route a stratified sample with the real policy model.

    Returns None (with the reason) when there is no configured provider, so the
    report can say why the column is missing instead of inventing numbers.
    """
    from jev_ultrafast import providers

    if sample_size <= 0:
        return None
    try:
        provider = providers.resolve("policy")
    except ValueError as error:
        return {"error": str(error), "rows": []}
    stride = max(1, len(cases) // sample_size)
    picked = cases[::stride][:sample_size]
    rows, tokens = [], 0
    for case in picked:
        time.sleep(GPT_PACING_SECONDS)
        started = time.perf_counter()
        try:
            content, meta = providers.chat(
                provider, ROUTING_SYSTEM, f"MISSION: {case['mission']}", max_tokens=200
            )
            answer = providers.extract_json(content).get("choice")
        except (ValueError, RuntimeError) as error:
            rows.append({**case, "model": None, "error": str(error)[:120]})
            continue
        usage = meta.get("usage") or {}
        tokens += sum(usage.get(field) or 0 for field in
                      ("input_tokens", "output_tokens", "prompt_tokens", "completion_tokens"))
        rows.append({
            **case,
            "model": answer,
            "latency_ms": round((time.perf_counter() - started) * 1000),
            "error": None,
        })
    scored = [row for row in rows if row.get("model")]
    return {
        "model": f"{provider['name']}:{provider['model']}",
        "rows": rows,
        "hits": sum(1 for row in scored if row["model"] == row["expected"]),
        "total": len(scored),
        "tokens": tokens,
        "stride": stride,
        "error": None,
    }


def _miss_table(rows, heading, limit=12):
    lines = [f"**{heading}**", "", "| Lang | Kind | Mission | Expected | Predicted |", "|---|---|---|---|---|"]
    for row in rows[:limit]:
        mission = row["mission"][:70].replace("|", "/")
        lines.append(f"| {row['lang']} | {row['kind']} | {mission}… | `{row['expected']}` | `{row['predicted']}` |")
    if len(rows) > limit:
        lines.append(f"| … | | *{len(rows) - limit} more* | | |")
    lines.append("")
    return lines


def render_report(composition, keyword_runs, stack, sample=None, note=None):
    lines = [
        "## 🎯 Routing battery — 241 labelled missions",
        "",
        f"{composition['total']} missions: {composition['core']} core "
        f"({composition['core_browser']} browser + {composition['core_orchestrated']} orchestrated) across "
        f"{len(composition['languages'])} languages, plus {composition['adversarial']} adversarial "
        f"(mixed intent, multi-clause, bilingual, telegraphic, typos).",
        "",
    ]
    if note:
        lines += [note, ""]

    if stack:
        lines += [
            "### Raw Laya vs the stack that actually runs",
            "",
            f"- **Raw Laya** (weights alone, gate ignored): **{stack['raw_hits']}/{stack['total']} "
            f"({_pct(stack['raw_hits'], stack['total'])})** of decided missions"
            + (f", {stack['raw_abstentions']} abstentions" if stack["raw_abstentions"] else ""),
            f"- **Effective stack** (Laya above the {stack['gate']:.2f} gate, keyword router below it): "
            f"**{stack['hits']}/{stack['total']} ({_pct(stack['hits'], stack['total'])})**",
            f"- **Dangerous confusion** (tool mission sent to the browser loop): "
            f"**{len(stack['dangerous'])}** ({_pct(len(stack['dangerous']), stack['total'])})",
            f"- Safe over-routing (page mission sent to the tool loop): {len(stack['over_routed'])}",
            f"- Decision latency p50/p95: Laya {_p50(stack['raw_ms']):.0f}/{_p95(stack['raw_ms']):.0f} ms · "
            f"stack {_p50(stack['latency_ms']):.0f}/{_p95(stack['latency_ms']):.0f} ms",
            f"- Laya status: `{stack['laya_status']}`",
            "",
            "| Lang | Cases | Effective | Dangerous | Over-routed |",
            "|---|---|---|---|---|",
        ]
        for language, bucket in stack["by_language"].items():
            lines.append(
                f"| {language} | {bucket['total']} | {_pct(bucket['hits'], bucket['total'])} "
                f"({bucket['hits']}/{bucket['total']}) | {bucket['dangerous']} | {bucket['over']} |"
            )
        lines.append("")
        for kind, bucket in stack["by_kind"].items():
            if kind == "core":
                continue
            lines.append(f"- Adversarial `{kind}`: {bucket['hits']}/{bucket['total']} correct, "
                         f"{bucket['dangerous']} dangerous")
        lines.append("")
        if stack["dangerous"]:
            lines += _miss_table(stack["dangerous"], "Dangerous confusions (cannot self-heal):", limit=15)
        if stack["over_routed"]:
            lines += _miss_table(stack["over_routed"], "Safe over-routing (completes, but slower):", limit=8)

    lines += ["### The keyword layer, measured side by side", "",
              "Same battery, same machine: the layer that shipped in 0.3.0 against the one "
              "shipping in 0.4.0 (both measured through the real `route_task`).", ""]
    lines += [
        "| Keyword layer | Accuracy | Dangerous | Over-routed | p50/p95 |",
        "|---|---|---|---|---|",
    ]
    for name, result in keyword_runs.items():
        lines.append(
            f"| {name} | {_pct(result['hits'], result['total'])} ({result['hits']}/{result['total']}) | "
            f"{len(result['dangerous'])} | {len(result['over_routed'])} | "
            f"{_p50(result['latency_ms']):.2f}/{_p95(result['latency_ms']):.2f} ms |"
        )
    lines.append("")
    # The shipped layer is the one that decides when Laya abstains, so its misses are
    # listed in full: a red build must show the exact missions to fix, not a count.
    shipped = keyword_runs[list(keyword_runs)[-1]]
    if shipped["dangerous"]:
        lines += _miss_table(shipped["dangerous"], "Dangerous confusions in the shipped keyword layer:", limit=20)
    if shipped["over_routed"]:
        lines += _miss_table(shipped["over_routed"], "Safe over-routing in the shipped keyword layer:", limit=10)

    if sample:
        if sample.get("error"):
            lines += ["### Policy-model cross-check", "", f"Skipped: {sample['error']}", ""]
        elif sample["rows"]:
            lines += [
                "### Policy-model cross-check (sampled)",
                "",
                f"`{sample['model']}` on a stratified sample of {sample['total']} missions "
                f"(every {sample['stride']}th case): **{sample['hits']}/{sample['total']} "
                f"({_pct(sample['hits'], sample['total'])})** · {sample['tokens']:,} tokens.",
                "",
            ]
            misses = [row for row in sample["rows"] if row.get("model") and row["model"] != row["expected"]]
            if misses:
                lines += _miss_table(
                    [{**row, "predicted": row["model"]} for row in misses],
                    "Policy-model misses on the sample:", limit=10,
                )
    return "\n".join(lines)


def laya_decider():
    """(choice, confidence, latency_ms) for the loaded weights, or (None, None, ms)."""
    from jev_ultrafast import laya_local

    def ask(mission):
        agent = laya_local.engine()
        if agent is None:
            return None, None, 0.0
        started = time.perf_counter()
        try:
            result = agent.predict({"mission": mission}, laya_local.ROUTE_QUESTIONS)
        except Exception:  # noqa: BLE001 - a failed prediction is an abstention, not a crash
            return None, None, round((time.perf_counter() - started) * 1000, 3)
        latency = round((time.perf_counter() - started) * 1000, 3)
        answer = (result.get("answers") or {}).get("route") or {}
        confidence = answer.get("confidence")
        return answer.get("choice"), (round(confidence, 3) if isinstance(confidence, (int, float)) else None), latency

    return ask


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--selftest", action="store_true",
                        help="keyword layers only: no weights download, no network, no keys")
    parser.add_argument("--case-limit", type=int, default=0, help="use only the first N cases")
    parser.add_argument("--cases", default="", help="JSONL fixture with extra labelled missions")
    parser.add_argument("--sample", type=int, default=0,
                        help="also route a sample with the policy model (needs a configured provider)")
    parser.add_argument("--json", default="", help="write the full results to this file")
    parser.add_argument("--floor", type=float, default=0.0,
                        help="exit 1 when effective accuracy is below this (default: report only)")
    parser.add_argument("--dangerous-max", type=int, default=-1,
                        help="exit 1 when dangerous confusion exceeds this count (default: report only)")
    args = parser.parse_args()

    from jev_ultrafast import orchestrator

    cases = list(ROUTING_CASES)
    if args.cases:
        cases += load_extra_cases(args.cases)
    if args.case_limit:
        cases = cases[: args.case_limit]
    composition = {**summary(), "total": len(cases)}

    keyword_runs = {
        f"0.3.0 baseline: ES/EN, {len(BASELINE_KEYWORDS)} keywords, substring rule":
            measure_keywords(cases, BASELINE_KEYWORDS, legacy=True),
        f"0.4.0 shipped: 6 languages, {len(orchestrator.ORCHESTRATED_KEYWORDS)} keywords, word-start rule":
            measure_keywords(cases, orchestrator.ORCHESTRATED_KEYWORDS),
    }

    stack = None
    note = None
    if args.selftest:
        note = ("Self-test mode: the real weights are not loaded (the sandbox has no access to "
                "huggingface.co), so the effective-column numbers come from the keyword layer alone. "
                "CI runs the same battery with the real weights.")
    else:
        from jev_ultrafast import laya_local

        if laya_local.engine() is None:
            note = f"Real weights unavailable ({laya_local.status()}); raw-Laya column omitted."
        else:
            stack = measure_stack(cases, laya_decider())

    sample = sample_with_policy_model(cases, args.sample) if args.sample else None
    report = render_report(composition, keyword_runs, stack, sample=sample, note=note)
    print(report)

    if args.json:
        payload = {
            "composition": composition,
            "languages": {name: {k: v for k, v in result.items() if k != "rows"}
                          for name, result in keyword_runs.items()},
            "effective": ({k: v for k, v in stack.items() if k not in {"rows", "dangerous", "over_routed"}}
                          if stack else None),
            "stack_rows": stack["rows"] if stack else [],
            "stack_dangerous": [{k: row[k] for k in ("id", "lang", "kind", "mission", "expected", "predicted")}
                                for row in (stack["dangerous"] if stack else [])],
            "sample": sample,
            "case_rows": keyword_runs[list(keyword_runs)[1]]["rows"],
            "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        }
        destination = Path(args.json)
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(json.dumps(payload, indent=2, ensure_ascii=False))
        print(f"\nJSON written to {destination}")

    shipped = keyword_runs[list(keyword_runs)[-1]]
    effective = stack["accuracy"] if stack else shipped["accuracy"]
    dangerous = len(stack["dangerous"]) if stack else len(shipped["dangerous"])
    if args.floor and effective < args.floor:
        print(f"\n🔴 Effective accuracy {effective:.0%} is below the {args.floor:.0%} floor.")
        return 1
    if args.dangerous_max >= 0 and dangerous > args.dangerous_max:
        print(f"\n🔴 {dangerous} dangerous confusions exceed the allowed {args.dangerous_max}.")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
