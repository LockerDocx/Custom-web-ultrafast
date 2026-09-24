"""Normalized parameter schema, presets, and persisted model selection.

Models are data, not branches: the sidebar renders its controls from a schema,
presets map to per-role parameter values, and the user's selection is persisted
to artifacts/model-config.json and re-applied over .env at startup.

MVP-1 repair: the schema is per model, not global. `schema_for_model` combines
the provider dialect, the discovered capabilities, family rules (data, not
`if model == X` branches) and runtime probe results into the exact parameter
surface one model accepts; `schema_for_role` resolves it for a role's current
model and the sidebar renders only those controls (spec §4.2, §5).
"""

import json
import os
import re
import time
from pathlib import Path

CONFIG_PATH = Path(os.environ.get("JEV_MODEL_CONFIG", "artifacts/model-config.json"))

ROLE_ENV_PREFIX = {"planner": "PLANNER", "policy": "POLICY", "text": "TEXT_MODEL"}

# ── the parameter catalogue (spec §2.3, §5.2) ────────────────────────────────
# `advanced` parameters stay hidden behind the advanced section by default.

PARAMETER_CATALOG = {
    "reasoning": {
        "type": "enum",
        "values": ["none", "low", "medium", "high"],
        "labels": {"none": "Off", "low": "Low", "medium": "Medium", "high": "High"},
        "description": "Thinking budget; low is fastest",
        "advanced": False,
    },
    "temperature": {
        "type": "number",
        "min": 0,
        "max": 2,
        "step": 0.1,
        "optional": True,
        "description": "Creativity; omit for the provider default",
        "advanced": False,
    },
    "stream": {
        "type": "boolean",
        "default": True,
        "description": "Stream the reply as it is generated",
        "advanced": False,
    },
    "max_tokens": {
        "type": "integer",
        "min": 1,
        "max": 131072,
        "optional": True,
        "description": "Output budget; empty means the context-aware default",
        "advanced": True,
    },
    "top_p": {
        "type": "number",
        "min": 0,
        "max": 1,
        "step": 0.05,
        "optional": True,
        "description": "Nucleus sampling cutoff",
        "advanced": True,
    },
    "seed": {
        "type": "integer",
        "optional": True,
        "description": "Deterministic sampling seed",
        "advanced": True,
    },
    "stop": {
        "type": "array",
        "optional": True,
        "description": "Stop sequences (comma separated)",
        "advanced": True,
    },
    "frequency_penalty": {
        "type": "number",
        "min": -2,
        "max": 2,
        "step": 0.1,
        "optional": True,
        "description": "Penalise repeated tokens",
        "advanced": True,
    },
    "presence_penalty": {
        "type": "number",
        "min": -2,
        "max": 2,
        "step": 0.1,
        "optional": True,
        "description": "Penalise tokens already present",
        "advanced": True,
    },
}

# Which catalogue parameters each request dialect can carry (spec §5.1).
DIALECT_PARAMS = {
    "openai": [
        "temperature", "top_p", "max_tokens", "stream", "seed", "stop",
        "frequency_penalty", "presence_penalty",
    ],
    "anthropic": ["temperature", "top_p", "max_tokens", "stream", "stop"],
}

# Family rules are data keyed by model-id substring, never code branches.
# reasoning_effort values follow each family's published contract (spec §5.1).
FAMILY_RULES = (
    ("kimi-k", {"reasoning_values": ["low", "high", "max"]}),
    ("kimi_k", {"reasoning_values": ["low", "high", "max"]}),
)

ROLES = [
    {"key": "planner", "label": "Planner", "hint": "Decomposes the mission once"},
    {"key": "policy", "label": "Executor", "hint": "Picks each action"},
    {"key": "text", "label": "Text writer", "hint": "Fills text fields"},
]

# The global view kept for compatibility: roles plus the full catalogue.
PARAMETER_SCHEMA = {"roles": ROLES, "parameters": PARAMETER_CATALOG}

ROLE_PARAM_ENV = {
    (role, name): f"{ROLE_ENV_PREFIX[role]}_{name.upper()}"
    for role in ROLE_ENV_PREFIX
    for name in PARAMETER_CATALOG
}

PRESETS = {
    "fast": {
        "label": "Fast",
        "description": "Lowest latency; minimal thinking",
        "params": {
            "planner": {"reasoning": "low"},
            "policy": {"reasoning": "low"},
            "text": {"reasoning": "low"},
        },
    },
    "balanced": {
        "label": "Balanced",
        "description": "General-purpose defaults",
        "params": {
            "planner": {"reasoning": "medium"},
            "policy": {"reasoning": "low"},
            "text": {"reasoning": "low"},
        },
    },
    "deep": {
        "label": "Deep",
        "description": "Heavy reasoning for complex research or planning",
        "params": {
            "planner": {"reasoning": "high"},
            "policy": {"reasoning": "medium"},
        },
    },
    "browser": {
        "label": "Browser",
        "description": "Conservative, fast browser interaction",
        "params": {
            "planner": {"reasoning": "low"},
            "policy": {"reasoning": "low"},
            "text": {"reasoning": "low"},
        },
    },
    "coding": {
        "label": "Coding",
        "description": "Precise output for code and files",
        "params": {
            "planner": {"reasoning": "high"},
            "policy": {"reasoning": "medium", "temperature": 0.2},
            "text": {"temperature": 0.2},
        },
    },
}

ROLE_MODEL_ENV = {
    "planner": ("PLANNER_PROVIDER", "PLANNER_MODEL"),
    "policy": ("POLICY_PROVIDER", "POLICY_MODEL"),
    "text": ("TEXT_MODEL_PROVIDER", "TEXT_MODEL"),
}


# ── per-model schemas (MVP-1) ─────────────────────────────────────────────────


def _family_rules(model_id):
    lowered = (model_id or "").lower()
    rules = {}
    for marker, overrides in FAMILY_RULES:
        if marker in lowered:
            rules.update(overrides)
    return rules


def _reasoning_marker(model_id):
    from . import discovery

    return discovery._capabilities(model_id or "")["reasoning"]


def schema_for_model(provider_name, model_id, capabilities=None, probed=None):
    """The exact parameter surface one model accepts, as a renderable schema.

    Combines, per spec §4.2: the provider dialect (what its API can carry),
    the discovered capabilities (reasoning only for reasoning models), family
    rules (published per-family controls) and runtime probe results (a probe
    that rejected a parameter removes it; a probe that accepted one adds it).
    """
    from . import providers

    dialect = providers.PROVIDERS.get(provider_name, {}).get("dialect", "openai")
    supported = list(DIALECT_PARAMS.get(dialect, DIALECT_PARAMS["openai"]))
    if capabilities is None:
        capabilities = {"reasoning": _reasoning_marker(model_id)}
    names = [name for name in supported]
    if capabilities.get("reasoning"):
        names.insert(0, "reasoning")
    probed = probed or {}
    for name, accepted in probed.items():
        if name not in PARAMETER_CATALOG:
            continue
        if accepted and name not in names:
            names.append(name)
        if not accepted and name in names:
            names.remove(name)
    parameters = {}
    for name in names:
        definition = dict(PARAMETER_CATALOG[name])
        if name == "reasoning":
            values = _family_rules(model_id).get("reasoning_values") or list(PARAMETER_CATALOG["reasoning"]["values"])
            definition["values"] = values
            definition["labels"] = {
                value: PARAMETER_CATALOG["reasoning"]["labels"].get(value, value) for value in values
            }
        parameters[name] = definition
    return {
        "provider": provider_name,
        "model": model_id,
        "dialect": dialect,
        "parameters": parameters,
        "simple": [name for name in parameters if not parameters[name].get("advanced")],
        "advanced": [name for name in parameters if parameters[name].get("advanced")],
    }


def _registry_entry(provider_name, model_id):
    from . import discovery

    registry = discovery._load_registry()
    for report in ((registry or {}).get("providers") or {}).values():
        for entry in (report or {}).get("models") or []:
            if entry.get("provider") == provider_name and entry.get("id") == model_id:
                return entry
    return None


def schema_for_role(role):
    """The schema of the model one role resolves to right now.

    With no model selected the full catalogue is offered: .env-level setup must
    keep working before any discovery has run.
    """
    if role not in ROLE_MODEL_ENV:
        raise ValueError(f"Unknown role: {role}")
    provider_env, model_env = ROLE_MODEL_ENV[role]
    provider_name = os.environ.get(provider_env, "")
    model_id = os.environ.get(model_env, "")
    if not provider_name or not model_id:
        return {
            "provider": provider_name,
            "model": model_id,
            "dialect": "openai",
            "parameters": {name: dict(definition) for name, definition in PARAMETER_CATALOG.items()},
            "simple": [name for name, d in PARAMETER_CATALOG.items() if not d.get("advanced")],
            "advanced": [name for name, d in PARAMETER_CATALOG.items() if d.get("advanced")],
            "fallback": True,
        }
    entry = _registry_entry(provider_name, model_id)
    capabilities = (entry or {}).get("capabilities")
    probed = (entry or {}).get("probedParams")
    return schema_for_model(provider_name, model_id, capabilities=capabilities, probed=probed)


def sidebar_schema():
    """What the sidebar needs to render model-specific controls (spec §5.3)."""
    return {
        "roles": ROLES,
        "parameters": PARAMETER_CATALOG,
        "modelSchemas": {role["key"]: schema_for_role(role["key"]) for role in ROLES},
    }


def _coerce(name, value, schema):
    kind = schema["type"]
    if kind == "enum":
        if value not in schema["values"]:
            raise ValueError(f"{name} must be one of {schema['values']}")
        return value
    if kind == "boolean":
        if isinstance(value, bool):
            return value
        text = str(value).strip().lower()
        if text in {"true", "on", "1", "yes"}:
            return True
        if text in {"false", "off", "0", "no"}:
            return False
        raise ValueError(f"{name} must be a boolean")
    if kind == "array":
        if isinstance(value, str):
            value = [part.strip() for part in value.split(",") if part.strip()]
        if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
            raise ValueError(f"{name} must be a list of strings")
        return value[:8]
    if kind == "integer":
        try:
            number = int(value)
        except (TypeError, ValueError):
            raise ValueError(f"{name} must be an integer") from None
        if "min" in schema and not schema["min"] <= number:
            raise ValueError(f"{name} must be at least {schema['min']}")
        if "max" in schema and not number <= schema["max"]:
            raise ValueError(f"{name} must be at most {schema['max']}")
        return number
    try:  # number
        number = float(value)
    except (TypeError, ValueError):
        raise ValueError(f"{name} must be a number") from None
    if not schema["min"] <= number <= schema["max"]:
        raise ValueError(f"{name} must be between {schema['min']} and {schema['max']}")
    return round(number, 2)


def _validate(role, params):
    if role not in {r["key"] for r in ROLES}:
        raise ValueError(f"Unknown role: {role}")
    if not isinstance(params, dict):
        raise ValueError("params must be an object")
    schema = schema_for_role(role)
    supported = schema["parameters"]
    label = schema.get("model") or "the selected model"
    cleaned = {}
    for name, value in params.items():
        if name not in supported:
            if name not in PARAMETER_CATALOG:
                raise ValueError(f"Unknown parameter: {name}")
            raise ValueError(f"{name} is not supported by {label}")
        if value is None:
            cleaned[name] = None  # explicit clear: fall back to the .env/default value
            continue
        cleaned[name] = _coerce(name, value, supported[name])
    return cleaned


def _encode(name, value):
    if isinstance(value, list):
        return json.dumps(value)
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)


def apply_params(role, params):
    """Validate against the role's current model and apply to env + config."""
    cleaned = _validate(role, params)
    config = load_config()
    stored = config.setdefault("params", {}).setdefault(role, {})
    for name, value in cleaned.items():
        env_name = ROLE_PARAM_ENV[(role, name)]
        if value is None:
            os.environ.pop(env_name, None)
            stored.pop(name, None)
        else:
            os.environ[env_name] = _encode(name, value)
            stored[name] = value
    save_config(config)
    return cleaned


def apply_preset(preset_key):
    if preset_key not in PRESETS:
        raise ValueError(f"Unknown preset: {preset_key}")
    applied = {}
    for role, params in PRESETS[preset_key]["params"].items():
        kept = {name: value for name, value in params.items() if name in schema_for_role(role)["parameters"]}
        applied[role] = apply_params(role, kept)
    return applied


def apply_model(role, provider_name, model_id):
    """Switch one role's provider+model in the environment and config file."""
    if role not in ROLE_MODEL_ENV:
        raise ValueError(f"Unknown role: {role}")
    model_id = model_id.strip()
    if not model_id or any(character.isspace() for character in model_id):
        raise ValueError("Invalid model id")  # colons are fine: Ollama tags look like qwen3.5:4b
    provider_env, model_env = ROLE_MODEL_ENV[role]
    os.environ[provider_env] = provider_name
    os.environ[model_env] = model_id.strip()
    config = load_config()
    config.setdefault("models", {})[role] = {"provider": provider_name, "model": model_id.strip()}
    save_config(config)


def prune_params(role):
    """Drop stored parameters the role's new model does not support (MVP-1).

    Switching from a reasoning model to a plain one must not leave a stale
    reasoning setting that the endpoint would then reject on every request.
    """
    supported = schema_for_role(role)["parameters"]
    config = load_config()
    stored = (config.get("params") or {}).get(role) or {}
    removed = {}
    for name in list(stored):
        if name not in supported:
            env_name = ROLE_PARAM_ENV.get((role, name))
            if env_name:
                os.environ.pop(env_name, None)
            removed[name] = stored.pop(name)
    if removed:
        config.setdefault("params", {})[role] = stored
        save_config(config)
    return removed


def save_profile(name):
    """Snapshot the current models + parameters as a named profile."""
    name = (name or "").strip()
    if not name or len(name) > 40:
        raise ValueError("Profile name must be 1-40 characters")
    selection = current_selection()
    config = load_config()
    config.setdefault("profiles", {})[name] = {
        "savedAt": time.time(),
        "models": {
            role: {"provider": data["provider"], "model": data["model"]}
            for role, data in selection.items()
            if data.get("provider") and data.get("model")
        },
        "params": {role: data.get("params") or {} for role, data in selection.items()},
    }
    save_config(config)
    return config["profiles"][name]


def apply_profile(name):
    """Restore a saved profile into the environment and the config file."""
    profile = (load_config().get("profiles") or {}).get((name or "").strip())
    if not profile:
        raise ValueError(f"Unknown profile: {name}")
    for role, selection in (profile.get("models") or {}).items():
        if role in ROLE_MODEL_ENV and selection.get("provider") and selection.get("model"):
            apply_model(role, selection["provider"], selection["model"])
    for role, params in (profile.get("params") or {}).items():
        if role in ROLE_MODEL_ENV and isinstance(params, dict):
            kept = {key: value for key, value in params.items() if value is not None}
            if kept:
                try:
                    apply_params(role, kept)
                except ValueError:
                    continue  # a profile may reference params the new model lacks
    return profile


def delete_profile(name):
    config = load_config()
    profiles = config.get("profiles") or {}
    if (name or "").strip() not in profiles:
        raise ValueError(f"Unknown profile: {name}")
    del profiles[(name or "").strip()]
    save_config(config)


def profile_names():
    return sorted((load_config().get("profiles") or {}).keys())


def load_config():
    try:
        data = json.loads(CONFIG_PATH.read_text())
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def save_config(config):
    CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    CONFIG_PATH.write_text(json.dumps(config, indent=2))


def apply_saved_config():
    """Re-apply the persisted model/parameter selection over the .env defaults."""
    config = load_config()
    for role, selection in (config.get("models") or {}).items():
        if role in ROLE_MODEL_ENV and isinstance(selection, dict):
            provider_name = selection.get("provider")
            model_id = selection.get("model")
            if provider_name and model_id:
                provider_env, model_env = ROLE_MODEL_ENV[role]
                os.environ.setdefault(provider_env, provider_name)
                os.environ[provider_env] = provider_name
                os.environ[model_env] = model_id
    for role, params in (config.get("params") or {}).items():
        if role in ROLE_MODEL_ENV and isinstance(params, dict):
            for name, value in params.items():
                env_name = ROLE_PARAM_ENV.get((role, name))
                if env_name is not None and value is not None:
                    os.environ[env_name] = _encode(name, value)
    return config


def current_selection():
    """What each role resolves to right now, for the sidebar."""
    from . import providers

    selection = {}
    for role, (provider_env, model_env) in ROLE_MODEL_ENV.items():
        provider_name = os.environ.get(provider_env, "")
        model = os.environ.get(model_env, "")
        params = {}
        for name in PARAMETER_CATALOG:
            env_name = ROLE_PARAM_ENV.get((role, name))
            value = os.environ.get(env_name, "") if env_name else ""
            if value:
                params[name] = value
        selection[role] = {
            "provider": provider_name,
            "model": model,
            "params": params,
            "display": _display_name(model),
            "dialect": providers.PROVIDERS.get(provider_name, {}).get("dialect", "openai"),
        }
    return selection


def _display_name(model_id):
    if not model_id:
        return "—"
    tail = model_id.rsplit("/", 1)[-1].replace("_", "-")
    words = re.split(r"-", tail)  # keep dots: "glm-5.3" → "GLM 5.3"
    acronyms = {"glm", "gpt", "llama", "qwen", "kimi", "oss", "ai", "vl", "nemotron", "devstral"}
    return " ".join(w.upper() if w.lower() in acronyms else (w[:1].upper() + w[1:]) for w in words if w)
