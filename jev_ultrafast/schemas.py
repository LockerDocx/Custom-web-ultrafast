"""Per-model parameter schemas: what each model actually accepts, as data.

NVIDIA NIM's catalogue moves every week and every model exposes a different
surface — Kimi takes ``reasoning_effort: low|high|max``, GLM toggles thinking
through ``chat_template_kwargs``, DeepSeek-R1 always reasons, an Anthropic
endpoint takes none of them. The spec's rule is "models are data, not branches
in the code", so this module holds three layers and no ``if model ==``:

1. ``BASE_PARAMETERS`` — the normalized parameter vocabulary (spec §5.2).
2. ``RULES`` — declarative family rules matched on provider/dialect/model id
   that add, restrict or remove parameters and say how ``reasoning`` is wired.
3. runtime evidence — parameters a live endpoint rejected (recorded by the
   request layer) or accepted (recorded by the discovery probe), persisted in
   ``artifacts/model-runtime.json``.

``schema_for()`` folds the three together into the schema the sidebar renders
and the validator enforces, and ``to_body()`` turns validated values into the
wire parameters for that specific model.
"""

import json
import os
import re
import threading
import time
from pathlib import Path

RUNTIME_PATH = Path(os.environ.get("JEV_MODEL_RUNTIME", "artifacts/model-runtime.json"))
_RUNTIME_LOCK = threading.Lock()

# ── 1. the normalized vocabulary ────────────────────────────────────────────
# tier: "simple" renders on the main surface, "advanced" hides behind the
# disclosure (spec §2.3). api: the OpenAI-compatible field a value maps to;
# reasoning is special-cased by the rules because every family wires it
# differently.
BASE_PARAMETERS = {
    "reasoning": {
        "type": "enum",
        "values": ["none", "low", "medium", "high"],
        "labels": {"none": "Off", "low": "Low", "medium": "Medium", "high": "High"},
        "label": "Reasoning",
        "tier": "simple",
        "description": "Thinking budget; low is fastest",
    },
    "temperature": {
        "type": "number",
        "min": 0,
        "max": 2,
        "step": 0.1,
        "optional": True,
        "label": "Creativity",
        "tier": "simple",
        "api": "temperature",
        "description": "Creativity; omit for the provider default",
    },
    "max_tokens": {
        "type": "integer",
        "min": 1,
        "max": 131072,
        "step": 1,
        "optional": True,
        "label": "Output limit",
        "tier": "simple",
        "api": "max_tokens",
        "description": "Upper bound on generated tokens",
    },
    "stream": {
        "type": "boolean",
        "optional": True,
        "label": "Streaming",
        "tier": "simple",
        "api": "stream",
        "description": "Show the answer as it is generated",
    },
    "top_p": {
        "type": "number",
        "min": 0,
        "max": 1,
        "step": 0.05,
        "optional": True,
        "label": "Top-p",
        "tier": "advanced",
        "api": "top_p",
        "description": "Nucleus sampling; leave empty unless you know you need it",
    },
    "seed": {
        "type": "integer",
        "min": 0,
        "max": 2**31 - 1,
        "step": 1,
        "optional": True,
        "label": "Seed",
        "tier": "advanced",
        "api": "seed",
        "description": "Fixed seed for repeatable runs",
    },
    "stop": {
        "type": "array",
        "items": "string",
        "maxItems": 4,
        "optional": True,
        "label": "Stop sequences",
        "tier": "advanced",
        "api": "stop",
        "description": "Up to 4 strings that end the generation",
    },
    "frequency_penalty": {
        "type": "number",
        "min": -2,
        "max": 2,
        "step": 0.1,
        "optional": True,
        "label": "Frequency penalty",
        "tier": "advanced",
        "api": "frequency_penalty",
        "description": "Discourages repeating the same tokens",
    },
    "presence_penalty": {
        "type": "number",
        "min": -2,
        "max": 2,
        "step": 0.1,
        "optional": True,
        "label": "Presence penalty",
        "tier": "advanced",
        "api": "presence_penalty",
        "description": "Discourages repeating the same topics",
    },
}

# Parameters every chat endpoint is assumed to take until proven otherwise.
_OPENAI_BASELINE = ["temperature", "max_tokens", "stream", "top_p", "seed", "stop",
                    "frequency_penalty", "presence_penalty"]

# ── 2. family rules ─────────────────────────────────────────────────────────
# Each rule matches on dialect, provider and/or a regex over the model id, and
# then edits the schema being built. Rules apply in order, generic first, so a
# family rule can override a provider rule. Adding a model family is a dict,
# never a branch.
#
#   keep      — restrict the parameter set to this list
#   drop      — remove these parameters
#   override  — merge these fragments into the parameter definitions
#   reasoning — how the reasoning enum reaches the wire for this family
#   schema    — schema id fragment, so the registry can name the surface
RULES = [
    {
        "id": "openai-compatible",
        "match": {"dialect": "openai"},
        "keep": _OPENAI_BASELINE,
        "schema": "openai",
    },
    {
        "id": "anthropic",
        "match": {"dialect": "anthropic"},
        "keep": ["temperature", "max_tokens", "stream", "top_p", "stop"],
        "reasoning": None,
        "schema": "anthropic",
    },
    {
        "id": "gemini-openai",
        "match": {"provider": ("gemini",)},
        "drop": ["frequency_penalty", "presence_penalty", "seed"],
        "schema": "gemini",
    },
    # Reasoning wiring. "effort" sends reasoning_effort, "template" sends
    # chat_template_kwargs={"thinking": bool}, "always" means the model reasons
    # and the control is pointless, None means there is nothing to send.
    {
        "id": "openai-effort",
        "match": {"provider": ("openai",)},
        "reasoning": {"style": "effort", "values": ["low", "medium", "high"]},
        "schema": "openai-effort",
    },
    {
        "id": "groq-effort",
        "match": {"provider": ("groq",)},
        "reasoning": {"style": "effort", "values": ["none", "low", "medium", "high"], "off": "low"},
        "schema": "groq",
    },
    {
        "id": "openrouter-effort",
        "match": {"provider": ("openrouter",)},
        "reasoning": {"style": "openrouter", "values": ["none", "low", "medium", "high"]},
        "schema": "openrouter",
    },
    {
        "id": "deepseek-thinking",
        "match": {"provider": ("deepseek",)},
        "reasoning": {"style": "deepseek", "values": ["none", "high"]},
        "schema": "deepseek",
    },
    {
        "id": "gpt-oss",
        "match": {"model": r"gpt-oss"},
        "reasoning": {"style": "effort", "values": ["low", "medium", "high"]},
        "schema": "gpt-oss",
    },
    {
        "id": "kimi",
        "match": {"model": r"kimi-k\d"},
        # The Kimi playground surface exposes reasoning_effort low/high/max and
        # not the penalty/top_p controls (spec §5.1).
        "drop": ["top_p", "frequency_penalty", "presence_penalty", "stop"],
        "reasoning": {
            "style": "effort",
            "values": ["low", "high", "max"],
            "labels": {"low": "Low", "high": "High", "max": "Max"},
        },
        "schema": "kimi",
    },
    {
        "id": "glm",
        "match": {"model": r"\bglm-\d"},
        "reasoning": {"style": "template", "values": ["none", "low", "medium", "high"], "on_from": "low"},
        "schema": "glm",
    },
    {
        "id": "qwen-thinking",
        "match": {"model": r"qwen3|qwq"},
        "reasoning": {"style": "template", "values": ["none", "low", "medium", "high"], "on_from": "low"},
        "schema": "qwen",
    },
    {
        "id": "nemotron",
        "match": {"model": r"nemotron"},
        "reasoning": {"style": "template", "values": ["none", "low", "medium", "high"], "on_from": "low"},
        "schema": "nemotron",
    },
    {
        "id": "deepseek-r1",
        "match": {"model": r"deepseek-r\d"},
        # R1-style models always emit a thinking block; there is no budget knob.
        "reasoning": "always",
        "schema": "deepseek-r",
    },
]

REASONING_ORDER = ["none", "low", "medium", "high", "max"]

# One prefix per role; every parameter gets "<PREFIX>_<PARAMETER>" in the
# environment (PLANNER_REASONING, POLICY_TOP_P, TEXT_MODEL_MAX_TOKENS, ...).
ROLE_ENV_PREFIX = {"planner": "PLANNER", "policy": "POLICY", "text": "TEXT_MODEL"}


def env_name(role, parameter):
    """The environment variable carrying one role's parameter."""
    prefix = ROLE_ENV_PREFIX.get(role)
    return f"{prefix}_{parameter.upper()}" if prefix else ""


def _matches(rule, provider, model_id, dialect):
    match = rule.get("match", {})
    if "dialect" in match and dialect != match["dialect"]:
        return False
    if "provider" in match and provider not in match["provider"]:
        return False
    pattern = match.get("model")
    if pattern and not re.search(pattern, model_id, re.IGNORECASE):
        return False
    return True


def schema_for(provider, model_id, capabilities=None, dialect="openai", runtime=None):
    """The parameter surface for one concrete model.

    Returns ``{"schemaId", "parameters", "reasoning", "sources", "unsupported"}``
    where ``parameters`` is the subset of :data:`BASE_PARAMETERS` this model
    accepts, already narrowed by family rules, declared capabilities and any
    runtime evidence collected from the live endpoint.
    """
    provider = (provider or "").strip().lower()
    model_id = (model_id or "").strip()
    dialect = dialect or "openai"
    names = list(_OPENAI_BASELINE) if dialect == "openai" else ["temperature", "max_tokens", "stream"]
    overrides = {}
    reasoning_rule = "unset"
    sources = []
    for rule in RULES:
        if not _matches(rule, provider, model_id, dialect):
            continue
        sources.append(rule["id"])
        if rule.get("keep"):
            names = [name for name in rule["keep"]]
        for name in rule.get("drop", ()):
            if name in names:
                names.remove(name)
        for name, fragment in (rule.get("override") or {}).items():
            overrides.setdefault(name, {}).update(fragment)
        if "reasoning" in rule:
            reasoning_rule = rule["reasoning"]

    parameters = {}
    reasoning = _reasoning_schema(reasoning_rule, capabilities)
    if reasoning:
        parameters["reasoning"] = reasoning["schema"]
    for name in names:
        if name in BASE_PARAMETERS:
            parameters[name] = {**BASE_PARAMETERS[name], **overrides.get(name, {})}

    evidence = runtime if runtime is not None else runtime_evidence(provider, model_id)
    unsupported = [name for name in evidence.get("unsupported", []) if name in parameters]
    for name in unsupported:
        parameters.pop(name, None)
    verified = [name for name in evidence.get("verified", []) if name in parameters]
    for name in verified:
        parameters[name] = {**parameters[name], "verified": True}

    # the most specific family that matched names the surface: "kimi-v1",
    # "glm-v1", "gpt-oss-v1", "openai-v1" for a plain OpenAI-compatible model
    family = "generic"
    for rule in RULES:
        if rule.get("schema") and rule["id"] in sources:
            family = rule["schema"]
            if "model" in rule.get("match", {}):
                break  # a model-id rule beats a provider/dialect rule
    return {
        "schemaId": f"{family}-v1",
        "model": model_id,
        "provider": provider,
        "parameters": parameters,
        "capabilities": dict(capabilities or {}),
        "reasoning": (reasoning or {}).get("wire"),
        "sources": sources,
        "unsupported": unsupported,
        "verified": verified,
        "checkedAt": evidence.get("checkedAt"),
    }


def _reasoning_schema(rule, capabilities):
    """The reasoning control for a family, or None when the model has none."""
    if rule in (None, "always"):
        return None
    caps = capabilities or {}
    if caps and caps.get("reasoning") is False and not caps.get("inferred", False):
        return None  # the catalogue says this model does not reason
    if rule == "unset":
        if not caps.get("reasoning"):
            return None  # nothing in the id or the catalogue suggests reasoning
        rule = {"style": "effort", "values": ["none", "low", "medium", "high"]}
    values = rule.get("values") or BASE_PARAMETERS["reasoning"]["values"]
    labels = {**BASE_PARAMETERS["reasoning"]["labels"], "max": "Max", **(rule.get("labels") or {})}
    schema = {
        **BASE_PARAMETERS["reasoning"],
        "values": values,
        "labels": {value: labels.get(value, value.title()) for value in values},
    }
    return {"schema": schema, "wire": {k: v for k, v in rule.items() if k != "labels"}}


# ── 3. runtime evidence ─────────────────────────────────────────────────────


def _load_runtime():
    try:
        data = json.loads(RUNTIME_PATH.read_text())
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def _save_runtime(data):
    try:
        RUNTIME_PATH.parent.mkdir(parents=True, exist_ok=True)
        RUNTIME_PATH.write_text(json.dumps(data, indent=2, sort_keys=True))
    except OSError:
        pass  # evidence is an optimization; never break a run over it


def runtime_key(provider, model_id):
    return f"{(provider or '').strip().lower()}::{(model_id or '').strip()}"


def runtime_evidence(provider, model_id):
    """What the live endpoint has already told us about this model."""
    entry = _load_runtime().get(runtime_key(provider, model_id))
    return entry if isinstance(entry, dict) else {}


def record_unsupported(provider, model_id, parameter):
    """Remember that this endpoint rejected a parameter, so the UI stops offering it."""
    if not provider or not model_id or parameter not in BASE_PARAMETERS:
        return
    with _RUNTIME_LOCK:
        data = _load_runtime()
        entry = data.setdefault(runtime_key(provider, model_id), {})
        unsupported = set(entry.get("unsupported") or [])
        if parameter in unsupported:
            return
        unsupported.add(parameter)
        entry["unsupported"] = sorted(unsupported)
        entry["verified"] = sorted(set(entry.get("verified") or []) - {parameter})
        entry["checkedAt"] = time.time()
        _save_runtime(data)


def record_verified(provider, model_id, parameters):
    """Remember parameters a real request accepted."""
    parameters = [name for name in parameters if name in BASE_PARAMETERS]
    if not provider or not model_id or not parameters:
        return
    with _RUNTIME_LOCK:
        data = _load_runtime()
        entry = data.setdefault(runtime_key(provider, model_id), {})
        verified = set(entry.get("verified") or []) | set(parameters)
        unsupported = set(entry.get("unsupported") or []) - set(parameters)
        entry["verified"] = sorted(verified)
        entry["unsupported"] = sorted(unsupported)
        entry["checkedAt"] = time.time()
        _save_runtime(data)


def forget(provider, model_id):
    """Drop the evidence for one model (used before a fresh probe)."""
    with _RUNTIME_LOCK:
        data = _load_runtime()
        if data.pop(runtime_key(provider, model_id), None) is not None:
            _save_runtime(data)


# ── 4. values → wire parameters ─────────────────────────────────────────────


def coerce(name, value, schema=None):
    """Validate one value against its schema; returns the normalized value.

    Raises ValueError with a sidebar-readable message. ``None`` always passes
    through: it means "clear this control and use the provider default".
    """
    definition = schema or BASE_PARAMETERS.get(name)
    if definition is None:
        raise ValueError(f"Unknown parameter: {name}")
    if value is None or value == "":
        return None
    kind = definition["type"]
    if kind == "enum":
        text = str(value).strip().lower()
        if text not in definition["values"]:
            raise ValueError(f"{name} must be one of {definition['values']}")
        return text
    if kind == "boolean":
        text = str(value).strip().lower()
        if isinstance(value, bool):
            return value
        if text in {"1", "true", "on", "yes"}:
            return True
        if text in {"0", "false", "off", "no"}:
            return False
        raise ValueError(f"{name} must be true or false")
    if kind == "array":
        if isinstance(value, str):
            items = [part.strip() for part in value.split(",")]
        elif isinstance(value, (list, tuple)):
            items = [str(part).strip() for part in value]
        else:
            raise ValueError(f"{name} must be a list of strings")
        items = [item for item in items if item]
        if not items:
            return None
        limit = definition.get("maxItems", 4)
        if len(items) > limit:
            raise ValueError(f"{name} accepts at most {limit} values")
        return items
    try:
        number = float(value)
    except (TypeError, ValueError):
        raise ValueError(f"{name} must be a number") from None
    if not definition["min"] <= number <= definition["max"]:
        raise ValueError(f"{name} must be between {definition['min']} and {definition['max']}")
    if kind == "integer":
        if number != int(number):
            raise ValueError(f"{name} must be a whole number")
        return int(number)
    return round(number, 2)


def parse_env(name, raw, schema=None):
    """Read one parameter back from its environment variable; None when unusable."""
    try:
        return coerce(name, raw, schema)
    except ValueError:
        return None


def format_env(value):
    """Serialize a parameter value for the environment."""
    if isinstance(value, bool):
        return "on" if value else "off"
    if isinstance(value, (list, tuple)):
        return ",".join(str(item) for item in value)
    return str(value)


def reasoning_body(setting, wire, provider="", dialect="openai"):
    """Map the reasoning setting to this family's body parameters."""
    if dialect == "anthropic":
        return {}
    setting = (setting or "none").strip().lower()
    if not wire or wire == "always":
        return {}
    style = wire.get("style")
    values = wire.get("values") or REASONING_ORDER
    off = setting in {"none", "off", "disabled"}
    if not off and setting not in values:
        setting = _closest(setting, values)  # "medium" on a low/high/max family
        if setting is None:
            return {}
    if style == "effort":
        if off:
            fallback = wire.get("off")
            return {"reasoning_effort": fallback} if fallback else {}
        return {"reasoning_effort": setting}
    if style == "openrouter":
        return {"reasoning": {"enabled": False}} if off else {"reasoning": {"effort": setting}}
    if style == "deepseek":
        return {"thinking": {"type": "disabled" if off else "enabled"}}
    if style == "template":
        on_from = wire.get("on_from", "low")
        enabled = not off and REASONING_ORDER.index(setting) >= REASONING_ORDER.index(on_from)
        return {"chat_template_kwargs": {"thinking": enabled}}
    return {}


def _closest(setting, values):
    """The nearest supported level when a preset asks for one the family lacks.

    Ties favour the higher budget: asking for "medium" on Kimi's low/high/max
    ladder should not quietly downgrade a deep-reasoning preset.
    """
    if setting in values:
        return setting
    if setting not in REASONING_ORDER:
        return None
    wanted = REASONING_ORDER.index(setting)
    ranked = [value for value in values if value in REASONING_ORDER]
    if not ranked:
        return None
    return min(ranked, key=lambda value: (abs(REASONING_ORDER.index(value) - wanted), -REASONING_ORDER.index(value)))


def to_body(params, schema, omit=(), max_tokens_field="max_tokens"):
    """Turn validated parameter values into body fields for this model."""
    body = {}
    definitions = schema.get("parameters", {})
    for name, value in (params or {}).items():
        if value is None or name in omit or name not in definitions:
            continue
        if name == "reasoning":
            body.update(reasoning_body(value, schema.get("reasoning"), schema.get("provider", "")))
            continue
        field = definitions[name].get("api", name)
        if name == "max_tokens":
            field = max_tokens_field
        body[field] = value
    return body
