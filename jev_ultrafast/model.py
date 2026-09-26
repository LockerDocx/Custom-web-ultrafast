"""The policy chooses via TypeSafe Jev or any configured provider; a small model writes field values."""

import json
import math
import os
import re
import time

import httpx

from . import providers
from .questions import MAX_PLAN_STEPS, NEXT_ACTION, PLANNER_SYSTEM, POLICY_SYSTEM, TARGET, TEXT_VALUE
from .redact import redact

# How long to wait for an answer before the endpoint is called dead, and how many times to
# ask. 25 s was measured as too short for the free tiers this app is built on: on 2026-09-25
# NVIDIA NIM left three 25 s attempts hanging for the planner and the executor (76 s each)
# while the same key answered a 37.8 s call for the text role in the same check — a cold
# start or a queue, not a bad key. A wrong key is answered with HTTP 401, which is reported
# as such; a stall is not. JEV_HTTP_TIMEOUT overrides the default.
DEFAULT_TIMEOUT = 60.0
ATTEMPTS = 3


def timeout_seconds():
    """Seconds to wait for one answer: JEV_HTTP_TIMEOUT if it holds a positive number."""
    raw = (os.environ.get("JEV_HTTP_TIMEOUT") or "").strip()
    if raw:
        try:
            seconds = float(raw)
        except ValueError:
            seconds = 0.0
        if seconds > 0:
            return seconds
    return DEFAULT_TIMEOUT


def build_client():
    """The one HTTP client: patient on reads, quick on connecting to something unreachable."""
    return httpx.Client(http2=True, timeout=httpx.Timeout(timeout_seconds(), connect=15.0))


class _SharedClient:
    """The module's HTTP client, built on first use and rebuilt if JEV_HTTP_TIMEOUT changes.

    Built lazily on purpose: the key file is read into the environment at startup, which can
    happen after this module is imported, and a client frozen at import time would ignore a
    JEV_HTTP_TIMEOUT that came from .env. Anything that is not one of the three private names
    is forwarded to the live client (tests replace this object wholesale).
    """

    def __init__(self):
        self._client = None
        self._seconds = None

    def _current(self):
        seconds = timeout_seconds()
        if self._client is None or self._seconds != seconds:
            self._client = build_client()
            self._seconds = seconds
        return self._client

    def __getattr__(self, name):
        return getattr(self._current(), name)


CLIENT = _SharedClient()


# A rate limit is not a broken key and not a slow endpoint: the provider is telling us to come
# back later, and it usually says how much later. Until this was honoured, a run died on
# "Please try again in 1.319999999s" because the retries were 0.5 s and 1 s apart — the agent
# gave up a third of a second before the provider would have answered.
RATE_LIMIT_STATUS = {429, 529, 503}
RATE_LIMIT_ATTEMPTS = 4
RATE_LIMIT_WAIT_CAP = 30.0  # never make the user wait longer than this without asking
_WAIT_SAID = r"(?:try again|retry|retry_after|available again)[^0-9]{0,24}"
_AMOUNT = r"([0-9]+(?:\.[0-9]+)?)\s*(ms|milliseconds?|s|sec|seconds?|m|min|minutes?)"
_RETRY_HINT = re.compile(_WAIT_SAID + _AMOUNT, re.IGNORECASE)


def suggested_wait(response, attempt=0):
    """How long the provider itself asked us to wait, or None if it did not say.

    Reads `Retry-After` first (the standard header) and then the provider's own message, which
    is where Groq puts it ("Please try again in 1.32s"). Capped: a cap is a promise that the
    agent will not sit silent for minutes; the cap is reported in the message when it is hit.
    """
    headers = getattr(response, "headers", None)
    raw = ""
    try:
        raw = (headers or {}).get("retry-after") or ""
    except Exception:  # noqa: BLE001 - a stub response in a test has no headers
        raw = ""
    if str(raw).strip():
        try:
            return min(float(str(raw).strip()), RATE_LIMIT_WAIT_CAP)
        except ValueError:
            pass
    text = ""
    try:
        text = response.text or ""
    except Exception:  # noqa: BLE001 - same: a stub may not have .text
        text = ""
    match = _RETRY_HINT.search(text[:500])
    if not match:
        return None
    amount, unit = float(match.group(1)), match.group(2).lower()
    if unit.startswith("ms"):
        seconds = amount / 1000.0
    elif unit.startswith("m"):
        seconds = amount * 60.0
    else:
        seconds = amount
    return min(seconds + 0.25, RATE_LIMIT_WAIT_CAP)  # a hair of slack: clocks are not in step


def rate_limit_error(response, waited):
    """The message a rate limit deserves: capacity, not a bad key, and what to do about it."""
    detail = redact(" ".join((response.text or "").split()))[:300]
    return RuntimeError(
        f"Model provider rate limit (HTTP {response.status_code}) — this is capacity, not a key "
        f"problem: the free tier is spent for now and the agent waited {waited:.1f} s in total. "
        f"What to do: press Run again in a moment, or move this role to a key with more room "
        f"(POLICY_PROVIDER / POLICY_MODEL, TEXT_MODEL_PROVIDER / TEXT_MODEL). No action was "
        f"executed. Provider said: {detail}"
    )


def _no_answer(error, seconds):
    """The error a user sees when nothing came back: what happened, and that the key is fine."""
    if isinstance(error, httpx.TimeoutException):
        detail = (
            f"no answer within {seconds:g} s (each of {ATTEMPTS} attempts). The endpoint is slow or busy —"
            " this is not a rejected key: raise JEV_HTTP_TIMEOUT to wait longer."
        )
    else:
        detail = (
            f"the connection could not be established ({ATTEMPTS} attempts). Check the network, a proxy or a VPN."
        )
    return RuntimeError(f"Model connection failed; no action executed — {detail}")


def post_json(url, key, body, headers=None):
    seconds = timeout_seconds()
    waited = 0.0
    attempt = 0
    # A rate limit gets one more try than a wire failure: waiting is the whole point of it.
    limit = max(ATTEMPTS, RATE_LIMIT_ATTEMPTS)
    while attempt < limit:
        attempt += 1
        try:
            response = CLIENT.post(url, json=body, headers=headers or {"Authorization": f"Bearer {key}"})
        except httpx.HTTPError as error:
            # A model that is being woken up, or a blip on the wire: the same tries the
            # streaming path gives before giving up. Retrying cannot duplicate work here —
            # nothing was sent and accepted.
            if attempt < ATTEMPTS:
                time.sleep(0.5 * 2 ** (attempt - 1))
                continue
            raise _no_answer(error, seconds) from None
        if response.status_code in RATE_LIMIT_STATUS:
            hint = suggested_wait(response, attempt)
            pause = hint if hint is not None else 0.5 * 2 ** (attempt - 1)
            if attempt < RATE_LIMIT_ATTEMPTS:
                time.sleep(pause)
                waited += pause
                continue
            raise rate_limit_error(response, waited)
        if response.is_error:
            # Include the provider's own message so the exact cause is visible in the sidebar.
            detail = redact(" ".join(response.text.split()))[:300]
            raise RuntimeError(f"Model provider returned HTTP {response.status_code}: {detail}; no action executed.")
        try:
            return response.json()
        except ValueError:
            raise RuntimeError(
                "Model provider returned a non-JSON response; check that the base URL ends in /v1."
            ) from None
    raise RuntimeError("Model unavailable")


def post_stream(url, key, body, headers=None, on_delta=None):
    """POST one request and consume the SSE stream; returns (text, usage, model).

    Every text chunk is passed to on_delta as it arrives (reasoning chunks too,
    for the live "thinking" view — but only content builds the returned text).
    Raises the same RuntimeErrors as post_json so error handling stays uniform.
    Retries happen only before the first chunk, never mid-stream.
    """
    request_headers = headers or {"Authorization": f"Bearer {key}"}
    seconds = timeout_seconds()
    waited = 0.0
    attempt = 0
    limit = max(ATTEMPTS, RATE_LIMIT_ATTEMPTS)
    while attempt < limit:
        attempt += 1
        parts = []
        usage = {}
        model_id = None
        served = False
        try:
            with CLIENT.stream("POST", url, json=body, headers=request_headers) as response:
                if response.status_code in RATE_LIMIT_STATUS:
                    hint = suggested_wait(response, attempt)
                    pause = hint if hint is not None else 0.5 * 2 ** (attempt - 1)
                    if attempt < RATE_LIMIT_ATTEMPTS:
                        time.sleep(pause)
                        waited += pause
                        continue
                    raise rate_limit_error(response, waited)
                if response.is_error:
                    detail = redact(" ".join(response.read().decode("utf-8", "replace").split()))[:300]
                    raise RuntimeError(
                        f"Model provider returned HTTP {response.status_code}: {detail}; no action executed."
                    )
                for line in response.iter_lines():
                    content, usage_update, chunk_model, reasoning = _sse_chunk(line)
                    if model_id is None and chunk_model:
                        model_id = chunk_model
                    if usage_update:
                        usage.update(usage_update)
                    if reasoning and on_delta:
                        on_delta(reasoning)
                    if content:
                        served = True
                        parts.append(content)
                        if on_delta:
                            on_delta(content)
                return "".join(parts), usage, model_id
        except httpx.HTTPError as error:
            if served:
                raise RuntimeError("Model stream failed mid-response; no action executed.") from None
            if attempt < ATTEMPTS:
                time.sleep(0.5 * 2 ** (attempt - 1))
                continue
            raise _no_answer(error, seconds) from None
    raise RuntimeError("Model unavailable")


def _sse_chunk(line):
    """Parse one SSE line → (content, usage_update, model_id, reasoning).

    Handles the OpenAI shape (choices[].delta.content / delta.reasoning_content,
    used by any OpenAI-compatible server too) and the Anthropic event shape.
    """
    if not line or not line.startswith("data:"):
        return "", {}, None, ""
    payload = line[5:].strip()
    if not payload or payload == "[DONE]":
        return "", {}, None, ""
    try:
        event = json.loads(payload)
    except ValueError:
        return "", {}, None, ""
    if not isinstance(event, dict):
        return "", {}, None, ""
    model_id = event.get("model") if isinstance(event.get("model"), str) else None
    usage = event.get("usage") if isinstance(event.get("usage"), dict) else {}
    kind = event.get("type")
    if kind == "content_block_delta":  # Anthropic
        delta = event.get("delta") or {}
        thinking = delta.get("thinking") if isinstance(delta.get("thinking"), str) else ""
        return delta.get("text") or "", {}, model_id, thinking
    if kind == "message_start":
        message = event.get("message") or {}
        return "", message.get("usage") or {}, model_id, ""
    if kind == "message_delta":
        return "", event.get("usage") or {}, model_id, ""
    choices = event.get("choices") or []
    if choices:
        delta = (choices[0] or {}).get("delta") or {}
        reasoning = delta.get("reasoning_content") or delta.get("reasoning") or ""
        if not isinstance(reasoning, str):
            reasoning = ""
        if not usage:  # some servers nest usage inside the choice instead of the event
            nested = (choices[0] or {}).get("usage")
            if isinstance(nested, dict):
                usage = nested
        return delta.get("content") or "", usage, model_id, reasoning
    return "", usage, model_id, ""


def validate_choice(answer, ids):
    try:
        probabilities = answer["probabilities"]
        numbers = [*probabilities.values(), answer["confidence"]]
        valid = (
            answer["choice"] in ids
            and set(probabilities) == set(ids)
            and all(type(n) in (int, float) and math.isfinite(n) and 0 <= n <= 1 for n in numbers)
            and abs(sum(probabilities.values()) - 1) < 0.02
            and probabilities[answer["choice"]] >= max(probabilities.values()) - 1e-6
        )
    except (KeyError, TypeError, ValueError):
        valid = False
    if not valid:
        raise ValueError("Invalid TypeSafe response; no action executed.")
    return answer


def action_space(actions):
    """One index per observed element; each operation has its own valid target choices."""
    elements, indices, targets, controls = [], {}, {}, {}
    operations = {"click": "CLICK", "fill": "TYPE_TEXT", "select": "SELECT"}
    for action in actions:
        kind = action["kind"]
        if kind not in operations:
            controls[action["id"].upper()] = action
            continue
        node = action["node"]
        if node not in indices:
            index = str(len(elements) + 1)
            indices[node] = index
            element = {k: action[k] for k in ("role", "value", "checked", "selected", "expanded") if k in action}
            element.update(index=index, label=action["label"].split(" → ")[0], operations=[])
            if kind == "select":
                element["value"] = action.get("current_value", "")
                element["options"] = []
            elements.append(element)
        index = indices[node]
        operation = operations[kind]
        group = targets.setdefault(operation, {})
        element = elements[int(index) - 1]
        if operation not in element["operations"]:
            element["operations"].append(operation)
        target = index
        if kind == "select":
            target = f"{index}:{len(element['options']) + 1}"
            element["options"].append({"index": target, "label": action["label"], "value": action["value"]})
        group[target] = action
    return elements, targets, controls


def operation_catalog(targets, controls):
    labels = {
        "CLICK": "Click an element, button, menu option, autocomplete suggestion, or calendar day.",
        "TYPE_TEXT": "Enter or replace text in an editable field. A small LLM will supply the value from the goal.",
        "SELECT": "Select an observed dropdown value.",
    }
    operations = {key: labels[key] for key in targets}
    operations.update({key: value["label"] for key, value in controls.items()})
    operations.update(DONE="Every requirement is visibly satisfied.", BLOCKED="No supported operation can progress.")
    return operations


def choose(state, goal, history):
    """TypeSafe Jev when its key is present; otherwise the configured OpenAI-compatible/Anthropic provider."""
    if os.environ.get("TYPESAFE_API_KEY"):
        return typesafe_choose(state, goal, history)
    return provider_choose(state, goal, history)


def policy_description():
    if os.environ.get("TYPESAFE_API_KEY"):
        return os.environ.get("TYPESAFE_MODEL", "jev-latest")
    try:
        provider = providers.resolve("policy")
    except ValueError:
        return "no policy model configured"
    return f"{provider['name']}:{provider['model']}"


def typesafe_choose(state, goal, history):
    elements, targets, controls = action_space(state["actions"])
    operations = operation_catalog(targets, controls)
    questions = {
        "operation": {"type": "choice", "criteria": operations, "instructions": {"goal": goal, "rules": NEXT_ACTION}}
    }
    for operation, candidates in targets.items():
        questions[operation.lower() + "_target"] = {
            "type": "choice",
            "criteria": {
                index: {
                    "element": f"[{index}] {a['label']}",
                    "current_value": a.get("current_value", a.get("value", "")),
                    **{k: a[k] for k in ("role", "checked", "selected", "expanded") if k in a},
                }
                for index, a in candidates.items()
            },
            "instructions": {"goal": goal, "operation": operation, "rules": [NEXT_ACTION, TARGET]},
        }
    body = {
        "model": os.environ.get("TYPESAFE_MODEL", "jev-latest"),
        "state": {
            "page": {k: state[k] for k in ("url", "title", "text")},
            "elements": elements,
            "recent_actions": [
                {k: h.get(k) for k in ("action", "kind", "text", "page_changed")} for h in history[-10:]
            ],
        },
        "questions": questions,
    }
    started = time.perf_counter()
    result = post_json("https://api.typesafe.ai/v1/systemone", os.environ["TYPESAFE_API_KEY"], body)
    operation_answer = validate_choice(result["answers"].get("operation", {}), operations)
    operation = operation_answer["choice"]
    target = None
    target_answer = None
    probabilities = {}
    if operation in targets:
        # Unused target heads cannot cause an action. Validate the head selected by the operation.
        target_answer = validate_choice(result["answers"].get(operation.lower() + "_target", {}), targets[operation])
        target = target_answer["choice"]
        choice = targets[operation][target]["id"]
        probabilities = {a["id"]: target_answer["probabilities"][index] for index, a in targets[operation].items()}
    else:
        choice = controls[operation]["id"] if operation in controls else operation
        probabilities[choice] = operation_answer["probabilities"][operation]
    return {
        "choice": choice,
        "operation": operation,
        "target": target,
        "confidence": operation_answer["confidence"],
        "probabilities": probabilities,
        "operation_probabilities": operation_answer["probabilities"],
        "target_probabilities": target_answer["probabilities"] if target_answer else {},
        "target_confidence": target_answer["confidence"] if target_answer else None,
        "raw_answers": result["answers"],
        "model": result["model"],
        "usage": result.get("usage", {}),
        "latency_ms": round((time.perf_counter() - started) * 1000),
        "request": body,
        "provider": "typesafe",
    }


POLICY_TEXT_CHARS = 2500
FIELD_TEXT_CHARS = 2000


def _policy_request(goal, state, elements, operations, history):
    lines = [f"GOAL: {goal}", "", f"PAGE: {state['url']} — {state['title']}"]
    if state.get("text"):
        # The indexed element table below carries the actionable detail; the free text is
        # context. Measured on the live flights mission, sending all 6000 observed
        # characters cost most of a free tier's minute per decision, so the excerpt is
        # trimmed here and the full text stays in the page state for verification.
        lines.append(f"PAGE TEXT (excerpt): {state['text'][:POLICY_TEXT_CHARS]}")
    lines.append("")
    lines.append("ELEMENTS (index · role · label · current value · operations):")
    for element in elements:
        line = f"[{element['index']}] {element['role']} · {element['label']}"
        if element.get("value"):
            line += f" · value {json.dumps(element['value'])}"
        for key in ("checked", "selected", "expanded"):
            if element.get(key) is not None:
                line += f" · {key}={json.dumps(element[key])}"
        line += f" · ops: {', '.join(element['operations'])}"
        lines.append(line)
        for option in element.get("options", []):
            lines.append(f"    {option['index']} {json.dumps(option['label'])} → value {json.dumps(option['value'])}")
    lines.append("")
    lines.append("AVAILABLE OPERATIONS (choose exactly one):")
    lines.extend(f"{name}: {description}" for name, description in operations.items())
    lines.append("")
    recent = [
        f"{h['step']}. {h['action']} ({h['kind']}"
        + (f", typed {json.dumps(h['text'])}" if h.get("text") else "")
        + (") — page changed" if h.get("page_changed") else ") — no observed change")
        for h in history[-10:]
    ]
    lines.append("RECENT ACTIONS:" if recent else "RECENT ACTIONS: none")
    lines.extend(recent)
    return "\n".join(lines)


def _validate_llm_choice(answer, operations, targets):
    if not isinstance(answer, dict) or answer.get("operation") not in operations:
        raise ValueError("invalid operation")
    operation = answer["operation"]
    target = None
    if operation in targets:
        target = str(answer.get("target", "")).strip()
        if target not in targets[operation]:
            raise ValueError("invalid target")
    confidence = answer.get("confidence")
    if not (type(confidence) in (int, float) and 0 <= confidence <= 1):
        confidence = 1.0
    return operation, target, float(confidence)


def provider_choose(state, goal, history):
    """One request to the configured provider returns operation and target together."""
    elements, targets, controls = action_space(state["actions"])
    operations = operation_catalog(targets, controls)
    provider = providers.resolve("policy")
    user = _policy_request(goal, state, elements, operations, history)
    started = time.perf_counter()
    content, meta = None, None
    for attempt in range(2):
        message = user
        if attempt:
            message += "\n\nYour previous reply was rejected. Respond again with ONLY the JSON object."
        # Same reasoning as the text helper: a thinking model needs room for the
        # thought and the answer, and a truncated reply is an invalid choice.
        content, meta = providers.chat(provider, POLICY_SYSTEM, message, max_tokens=2048)
        try:
            answer = providers.extract_json(content)
            operation, target, confidence = _validate_llm_choice(answer, operations, targets)
            break
        except ValueError as error:
            if attempt:
                raise ValueError(f"Policy model returned an invalid choice ({error}); no action executed.") from None
    if target is not None:
        choice = targets[operation][target]["id"]
    else:
        choice = controls[operation]["id"] if operation in controls else operation
    return {
        "choice": choice,
        "operation": operation,
        "target": target,
        "confidence": confidence,
        "probabilities": {choice: confidence},
        "operation_probabilities": {},
        "target_probabilities": {},
        "target_confidence": confidence if target is not None else None,
        "raw_answers": answer,
        "model": meta["model"],
        "usage": meta.get("usage", {}),
        "latency_ms": round((time.perf_counter() - started) * 1000),
        "request": {
            "provider": provider["name"],
            "model": provider["model"],
            "messages": [
                {"role": "system", "content": POLICY_SYSTEM},
                {"role": "user", "content": user},
            ],
        },
        "provider": "llm",
    }


def field_context(goal, action, page, history):
    return {
        "goal": goal,
        "field": {k: action.get(k) for k in ("label", "role", "value")},
        "page": {"title": page["title"], "text": page["text"][:FIELD_TEXT_CHARS]},
        "recent_actions": [{k: h.get(k) for k in ("action", "text")} for h in history[-6:]],
    }


def field_text(context):
    provider = providers.resolve("text")
    request = json.dumps(context)
    started = time.perf_counter()
    content, meta = None, None
    for attempt in range(2):
        message = request
        if attempt:
            message += ('\n\nYour previous reply was rejected. The goal states the value this field needs: '
                        'reply with ONLY {"text": "that value, exactly as the goal writes it"}.')
        # A reasoning model spends part of this budget thinking, and a field value is
        # short: 1024 tokens was enough for the answer and not for the thinking, which is
        # how a two-attempt retry came back empty on the live mission.
        content, meta = providers.chat(provider, TEXT_VALUE, message, max_tokens=2048)
        try:
            output = providers.extract_json(content)
            value = output["text"]
            if set(output) != {"text"} or not isinstance(value, str) or not value.strip() or len(value) > 2000:
                raise ValueError()
        except (ValueError, KeyError, TypeError) as rejected:
            # Say what the model actually answered: "nothing typed" alone sent a maintainer
            # hunting through logs for a field this layer owns.
            sample = redact(" ".join((content or "").split()))[:160]
            why = f"{type(rejected).__name__}: {rejected}" if str(rejected) else "no usable text"
            last = f"last reply: {sample!r}" if sample else "last reply: empty"
            continue  # a small model answers {"text": null} now and then; ask once more
        return value, {
            "model": provider["model"],
            "latency_ms": round((time.perf_counter() - started) * 1000),
            "usage": meta.get("usage", {}),
        }
    raise ValueError(f"Text helper returned no valid field value ({why}; {last}); nothing typed.") from None


def planning_config():
    """The planner provider config, or None to keep the original single-goal loop.

    Enabled by configuration or derived from a free key (one key is enough to
    run the whole agent), so a fresh install plans its missions out of the box.
    """
    if not providers.planner_enabled():
        return None
    return providers.resolve("planner")


def _validate_steps(answer):
    steps = answer.get("steps") if isinstance(answer, dict) else None
    if not isinstance(steps, list) or not steps or len(steps) > MAX_PLAN_STEPS:
        raise ValueError("invalid steps")
    cleaned = []
    for step in steps:
        if not isinstance(step, str) or not step.strip() or len(step) > 500:
            raise ValueError("invalid step")
        cleaned.append(step.strip())
    return cleaned


def _planner_request(mission, page, *, reason=None, plan=None, plan_index=0, history=None):
    lines = ["MISSION: " + mission, "", f"PAGE: {page.get('url', '')} — {page.get('title', '')}"]
    if reason:
        done = ["  ✓ " + step for step in (plan or [])[:plan_index]]
        remaining = ["  ✗ " + step for step in (plan or [])[plan_index:]]
        lines += ["", "PREVIOUS PLAN (✓ completed, ✗ not completed):", *(done or ["  none"]), *remaining]
        lines += ["", "PROBLEM: " + reason]
        if history:
            lines += ["", "RECENT ACTIONS:"]
            lines += [f"{h.get('step', '')}. {h.get('action', '')} ({h.get('kind', '')})" for h in history[-6:]]
        lines += ["", "Produce a corrected plan for the REMAINING work only. Reply with the JSON steps list."]
    else:
        lines += ["", "Produce the ordered checklist of browser steps for the mission. Reply with the JSON steps list."]
    return "\n".join(lines)


PLANNER_ATTEMPTS = 2


def _ask_for_plan(provider, user):
    """One planner request, parsed and validated."""
    content, _meta = providers.chat(provider, PLANNER_SYSTEM, user, max_tokens=1024)
    return _validate_steps(providers.extract_json(content))


def _plan_with_one_retry(provider, user):
    """Ask for the plan, and ask once more when the reply came back unusable.

    Measured on 2026-09-25 (scripts/bench_profiles.py, 10 missions x 2 token budgets): one planner
    call in ten came back **empty** from NVIDIA's GLM endpoint - and at exactly the same rate with
    1024 and with 2048 tokens, so it is not a truncated answer and a bigger budget does not fix it.
    The planner runs once per mission, so a second try is cheap; losing the plan is not fatal (the
    agent falls back to the single-goal loop) but the checklist is worth one more question.

    Only an unusable *reply* is retried. A connection failure is already retried three times inside
    model.post_json and is raised here as it is.
    """
    last = None
    for _attempt in range(PLANNER_ATTEMPTS):
        try:
            return _ask_for_plan(provider, user)
        except ValueError as error:  # empty reply, unparseable JSON, or a rejected step list
            last = error
    raise last


def plan_steps(mission, page):
    """The planner decomposes the mission into a short ordered checklist of browser steps."""
    provider = providers.resolve("planner")
    return _plan_with_one_retry(provider, _planner_request(mission, page))


def replan_steps(mission, plan, plan_index, reason, page, history):
    """Replacement steps for the remaining plan after a blocked or stalled step."""
    provider = providers.resolve("planner")
    user = _planner_request(mission, page, reason=reason, plan=plan, plan_index=plan_index, history=history)
    return _plan_with_one_retry(provider, user)
