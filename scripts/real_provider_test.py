"""Real-provider test for the per-model parameter engine (MVP-1) against live APIs.

Run by `.github/workflows/real-provider-test.yml` with the repository secrets
(NVIDIA_API_KEY / GROQ_API_KEY), or locally with `.env`:

    uv run --env-file .env python scripts/real_provider_test.py

Unlike `check_providers.py` (which only proves connectivity), this exercises the
whole MVP-1 surface with real endpoints and real catalogues:

  1. catalogue  — discovery against the provider's real /v1/models (registry v2)
  2. surfaces   — the parameter surface resolved per real model, family rules included
  3. probe      — live compatibility probe: what the endpoint really accepts/refuses
  4. wiring     — role selection + parameters, exactly as the sidebar applies them
  5. real call  — one request per role carrying the applied parameters

Hard contract failures exit 1; provider-side hiccups (a spent quota, a model
retired upstream) are reported as warnings and never break the run. Credentials
are never printed.
"""

import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from jev_ultrafast import discovery, parameters, providers  # noqa: E402
from jev_ultrafast.firefox import load_environment  # noqa: E402

CONFIGURED = ("planner", "policy", "text")
# one family per pattern: each exercises a different rule in jev_ultrafast.schemas
INTERESTING = (
    "kimi", "glm", "gpt-oss", "deepseek-r1", "nemotron", "qwen3", "mistral-large", "llama-3.3", "gpt-5",
)
SAMPLE_LIMIT = 12
LIMIT_MARKERS = ("HTTP 429", "HTTP 529", "rate limit", "tokens per day", "tokens per minute", "quota")
# An endpoint that stalls leaves the probe with no verdict at all — that is the network,
# not the parameter engine, so the probe is asked again before the report calls it a
# failure. Parameter verdicts themselves are never softened: they stay a hard check.
CONNECTION_MARKERS = ("Model connection failed", "Model stream failed", "Model unavailable")
PROBE_ATTEMPTS = 3

RESULTS = []


def record(icon, title, detail=""):
    RESULTS.append((icon, title, detail))
    print(f"{icon} {title}" + (f" — {detail}" if detail else ""), flush=True)


def hard(title, condition, detail=""):
    """A contract the app guarantees: failing it is a red run."""
    if condition:
        record("✅", title, detail)
    else:
        record("❌", title, detail)
        hard.failed = True


hard.failed = False


def soft(title, detail=""):
    record("🟡", title, detail)


def provider_names():
    names = []
    for name, preset in providers.PROVIDERS.items():
        if preset.get("local") or not preset.get("base_url"):
            continue
        if any(os.environ.get(env, "").strip() for env in preset.get("key_env", [])):
            names.append(name)
    return names


def section(title):
    print(f"\n## {title}\n", flush=True)


def probe_with_retries(name, model_id):
    """Probe one model for its parameter verdict; retry a stall, never a verdict.

    An endpoint that never answers — a cold start, a load balancer, a hiccup on the wire —
    leaves the probe with nothing to report, and by then the HTTP layer has already spent
    its own three retries inside `discovery.probe_model` (76 s of waiting). That is the
    network, not the parameter engine, so the probe is asked again; the attempt count is
    reported, so a run that needed a retry never looks like one that did not. A parameter
    the endpoint refuses is a verdict and is passed straight through.

    Returns (report_or_None, attempts, milliseconds_spent_on_the_last_attempt).
    """
    attempts = 0
    while True:
        attempts += 1
        started = time.monotonic()
        try:
            report = discovery.probe_model(name, model_id)
        except Exception as error:  # noqa: BLE001
            soft(f"Probe failed for {name}/{model_id}", str(error)[:160])
            return None, attempts, round((time.monotonic() - started) * 1000)
        waited_ms = round((time.monotonic() - started) * 1000)
        stall = report.get("error") or ""
        verdictless = bool(stall) and any(marker in stall for marker in CONNECTION_MARKERS)
        if not verdictless or attempts >= PROBE_ATTEMPTS:
            return report, attempts, waited_ms
        pause = 10 * attempts
        print(
            f"| `{name}` | `{model_id}` | — | — | — | endpoint did not answer "
            f"(attempt {attempts} of {PROBE_ATTEMPTS}); retrying in {pause} s |",
            flush=True,
        )
        time.sleep(pause)


def main():
    load_environment()
    names = provider_names()
    print("# Real provider test", flush=True)
    print(f"\nProviders with a key: {', '.join(names) or 'none'} · Python {sys.version.split()[0]}", flush=True)
    if not names:
        soft("No provider key in this environment", "set NVIDIA_API_KEY / GROQ_API_KEY to run the real test")
        return finish()

    # ── 1. catalogue (registry v2) ──────────────────────────────────────────
    section("1. Catalogue — discovery against the real /v1/models")
    registry = {}
    try:
        registry = discovery.discover(refresh=True)
    except Exception as error:  # noqa: BLE001 - diagnostics must survive anything
        soft("Discovery failed", str(error)[:200])
    print("| Provider | Endpoint | Chat models | Registry fields |", flush=True)
    print("| --- | --- | --- | --- |", flush=True)
    catalogue = {}
    for name in names:
        entry = (registry.get("providers") or {}).get(name) or {}
        models = entry.get("models") or []
        catalogue[name] = models
        fields = sorted({key for model in models for key in model}) if models else []
        print(f"| `{name}` | {entry.get('endpoint') or '—'} | {len(models)} | {', '.join(fields)} |", flush=True)
    total = sum(len(models) for models in catalogue.values())
    hard(
        "Catalogue answered for every keyed provider",
        all(catalogue.get(n) for n in names),
        f"{total} chat models total",
    )
    if total:
        missing = [
            model["id"]
            for models in catalogue.values()
            for model in models
            if not model.get("parametersSchema") or not model.get("parameters") or not model.get("discoveredAt")
        ]
        hard(
            "Every catalogued model carries schemaId + parameters + discoveredAt",
            not missing,
            f"{len(missing)} incomplete",
        )
        hard("Registry is version 2", registry.get("version") == 2, f"version={registry.get('version')}")

    # ── 2. per-model surfaces ───────────────────────────────────────────────
    section("2. Per-model parameter surfaces")
    picks = []
    for pattern in INTERESTING:
        for name, models in sorted(catalogue.items()):
            match = next((m for m in models if pattern in m["id"].lower()), None)
            if match and not any(m["id"] == match["id"] for _n, m in picks):
                picks.append((name, match))
                break
    picks = picks[:SAMPLE_LIMIT]
    print("| Provider | Model | schemaId | reasoning values | body sent for reasoning=high | parameters |", flush=True)
    print("| --- | --- | --- | --- | --- | --- |", flush=True)
    for name, model in picks:
        dialect = providers.PROVIDERS[name].get("dialect", "openai")
        surface = providers.model_schema(name, model["id"], dialect)
        reasoning = surface.get("reasoning") or {}
        values = ", ".join(reasoning.get("values") or []) or "—"
        body = providers.reasoning_params("high", name, dialect, model["id"])
        wire = "`" + json.dumps(body, separators=(",", ":")) + "`" if body else "—"
        offered = ", ".join(sorted(surface["parameters"]))
        print(
            f"| `{name}` | `{model['id']}` | {surface['schemaId']} | {values} | {wire} | {offered} |",
            flush=True,
        )
    if picks:
        # A model that always reasons (DeepSeek-R1) has no budget knob: offering no
        # control there is the design, not a gap. Every model whose resolved spec
        # carries values, however, must expose the control.
        missing_control, always_reasoning = [], []
        for name, model in picks:
            surface = providers.model_schema(name, model["id"])
            wire = surface.get("reasoning")
            if isinstance(wire, dict) and wire.get("values") and "reasoning" not in surface["parameters"]:
                missing_control.append(model["id"])
            elif (model["capabilities"] or {}).get("reasoning") and not wire:
                always_reasoning.append(model["id"])
        hard(
            "Every controllable-reasoning model exposes the control",
            not missing_control,
            f"missing: {missing_control or 'none'}",
        )
        record(
            "✅" if always_reasoning else "🟡",
            "Always-reasoning models offer no knob (documented design)",
            f"{always_reasoning}" if always_reasoning else "none in this sample",
        )
        differing = {model["parametersSchema"] for _n, model in picks}
        record(
            "✅" if len(differing) > 1 else "🟡",
            "Surfaces really differ between models",
            f"schemaIds: {', '.join(sorted(differing))}",
        )

    # ── 3. live probe: what the endpoint accepts ────────────────────────────
    section("3. Live probe — the endpoint's own verdict")
    probes = []
    for name, models in catalogue.items():
        for model in models:
            if model["id"] in (os.environ.get("PLANNER_MODEL"), os.environ.get("POLICY_MODEL")):
                probes.append((name, model["id"]))
    if not probes:
        probes = [(name, models[0]["id"]) for name, models in catalogue.items() if models]
    print("| Provider | Model | probed | verified | refused | endpoint error |", flush=True)
    print("| --- | --- | --- | --- | --- | --- |", flush=True)
    for name, model_id in probes[:4]:
        report, attempts, waited_ms = probe_with_retries(name, model_id)
        if report is None:
            continue
        error = report.get("error") or "—"
        if error != "—" and any(marker.lower() in error.lower() for marker in LIMIT_MARKERS):
            error = f"quota exhausted: {error[:80]}"
        elif error != "—":
            # How long it waited says more than the message does: a 25 s failure is
            # the request timing out, an instant one is the connection being refused.
            error = f"{error} — {waited_ms} ms"
            if attempts > 1:
                error += f" · after {attempts} attempts"
        print(
            f"| `{name}` | `{model_id}` | {', '.join(report['probed']) or '—'} | "
            f"{', '.join(report['verified']) or '—'} | {', '.join(report['unsupported']) or '—'} | {error} |",
            flush=True,
        )
        hard(
            f"{model_id}: every probed parameter got a verdict",
            sorted(report["probed"]) == sorted(set(report["verified"]) | set(report["unsupported"])),
            f"verified={report['verified']} refused={report['unsupported']}",
        )
        if report["unsupported"]:
            after = providers.model_schema(name, model_id)
            hard(
                f"{model_id}: refused parameters leave the offered surface",
                not set(report["unsupported"]) & set(after["parameters"]),
                f"still offered: {sorted(set(report['unsupported']) & set(after['parameters'])) or 'none'}",
            )
        if report["verified"] and not report["error"]:
            hard(
                f"{model_id}: a real request carried the verified parameters",
                True,
                f"{len(report['verified'])} parameters accepted live",
            )

    # ── 4. role wiring, as the sidebar does it ──────────────────────────────
    section("4. Role wiring — selection + parameters as the sidebar applies them")
    print("| Role | Provider | Model | schemaId | parameters in force |", flush=True)
    print("| --- | --- | --- | --- | --- |", flush=True)
    for role in CONFIGURED:
        try:
            provider_name, model_id = parameters.model_for(role)
        except Exception as error:  # noqa: BLE001
            soft(f"{role}: no model configured", str(error)[:120])
            continue
        surface = parameters.role_schema(role)
        params = (parameters.current_selection()[role] or {}).get("params") or {}
        print(
            f"| {role} | `{provider_name}` | `{model_id}` | {surface.get('schemaId') or '—'} | "
            f"{', '.join(f'{k}={v}' for k, v in sorted(params.items())) or 'provider defaults'} |",
            flush=True,
        )
    # Switch the planner away and back: the same move the sidebar makes, which is
    # what prunes a parameter the new model does not have.
    try:
        configured = parameters.model_for("planner")
        candidates = [(name, model) for name, models in sorted(catalogue.items()) for model in models]
        interesting = [pair for pair in candidates if any(p in pair[1]["id"].lower() for p in INTERESTING)]
        target = next((pair for pair in interesting if (pair[0], pair[1]["id"]) != tuple(configured)), None)
        if target is None:
            target = next((pair for pair in candidates if (pair[0], pair[1]["id"]) != tuple(configured)), None)
        target = (target[0], target[1]["id"]) if target else None
        if target:
            removed = parameters.apply_model("planner", target[0], target[1])
            surface = parameters.current_selection()["planner"]
            hard(
                f"Switching to {target[0]}/{target[1]} resolves its own surface",
                bool(surface["schema"]["parameters"]),
                f"schemaId={surface['schema']['schemaId']} · pruned: {sorted(removed) or 'nothing'}",
            )
        removed = parameters.apply_model("planner", configured[0], configured[1])
        back = parameters.current_selection()["planner"]
        hard(
            "Switching back restores the configured model and its surface",
            back["model"] == configured[1] and bool(back["schema"]["parameters"]),
            f"back to {back['provider']}/{back['model']} · pruned: {sorted(removed) or 'nothing'}",
        )
    except Exception as error:  # noqa: BLE001
        soft("Could not switch the planner model", str(error)[:160])

    # ── 5. a real request per role, with the applied parameters ─────────────
    section("5. Real request per role")
    print("| Role | Model | Latency | Reply |", flush=True)
    print("| --- | --- | --- | --- |", flush=True)
    for role in CONFIGURED:
        try:
            if role == "planner":
                asked = {"reasoning": "high", "temperature": 0.3}
                wanted = parameters.supported_subset("planner", asked)
                applied = parameters.apply_params("planner", wanted) if wanted else {}
                skipped = sorted(set(asked) - set(wanted)) or "none"
                record("✅", f"{role}: parameters applied", f"{applied} (skipped: {skipped})")
            provider = providers.resolve(role)
            started = time.perf_counter()
            reply, meta = providers.chat(
                provider,
                "You are a connectivity check. Answer with the single word OK.",
                "Say OK.",
                max_tokens=64,
            )
            latency = round((time.perf_counter() - started) * 1000)
            text = (reply or "").strip().replace("|", "/")[:40]
            if (meta or {}).get("usage"):
                text += f" · {meta['usage'].get('total_tokens', '?')} tok"
            print(f"| {role} | `{provider['name']}:{provider['model']}` | {latency} ms | {text or '—'} |", flush=True)
            hard(f"{role}: the real endpoint answered", bool(text), f"{latency} ms")
        except Exception as error:  # noqa: BLE001
            detail = str(error).replace("|", "/")[:160]
            icon = "🟡" if any(marker.lower() in detail.lower() for marker in LIMIT_MARKERS) else "❌"
            record(icon, f"{role}: no answer", detail)
            if icon == "❌":
                hard.failed = True

    return finish()


def finish():
    failures = [row for row in RESULTS if row[0] == "❌"]
    warnings = [row for row in RESULTS if row[0] == "🟡"]
    print("\n## Verdict\n", flush=True)
    print(f"- checks passed: {len([r for r in RESULTS if r[0] == '✅'])}", flush=True)
    print(f"- warnings: {len(warnings)}", flush=True)
    print(f"- failures: {len(failures)}", flush=True)
    if failures:
        print("\n**Failures:**", flush=True)
        for _icon, title, detail in failures:
            print(f"- {title} — {detail}", flush=True)
    else:
        print("\n**All green: the per-model parameter engine works against the live APIs.**", flush=True)
    return 1 if hard.failed else 0


if __name__ == "__main__":
    sys.exit(main())
