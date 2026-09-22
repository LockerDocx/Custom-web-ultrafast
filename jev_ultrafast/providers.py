"""Any OpenAI-compatible or Anthropic-compatible endpoint can drive the policy and the text helper.

Roles: "policy" (operation + target choice) and "text" (TYPE_TEXT values). Each role reads
POLICY_* / TEXT_MODEL_* variables, falls back to the provider's own key variable
(OPENROUTER_API_KEY, NVIDIA_API_KEY, ...), and auto-detects the API dialect from the base URL.
"""

import json
import os
import re

PROVIDERS = {
    "openai": {
        "base_url": "https://api.openai.com/v1",
        "dialect": "openai",
        "key_env": ["OPENAI_API_KEY"],
        "json_mode": True,
    },
    "anthropic": {"base_url": "https://api.anthropic.com", "dialect": "anthropic", "key_env": ["ANTHROPIC_API_KEY"]},
    "openrouter": {
        "base_url": "https://openrouter.ai/api/v1",
        "dialect": "openai",
        "key_env": ["OPENROUTER_API_KEY"],
        "headers": {"X-Title": "custom-web-ultrafast"},
    },
    "nvidia": {
        "base_url": "https://integrate.api.nvidia.com/v1",
        "dialect": "openai",
        "key_env": ["NVIDIA_API_KEY", "NVIDIA_NIM_API_KEY"],
    },
    "omniroute": {"base_url": "http://localhost:20128/v1", "dialect": "openai", "key_env": ["OMNIROUTE_API_KEY"]},
    "deepseek": {
        "base_url": "https://api.deepseek.com/v1",
        "dialect": "openai",
        "key_env": ["DEEPSEEK_API_KEY"],
        "json_mode": True,
    },
    "groq": {
        "base_url": "https://api.groq.com/openai/v1",
        "dialect": "openai",
        "key_env": ["GROQ_API_KEY"],
        "json_mode": True,
    },
    "together": {
        "base_url": "https://api.together.xyz/v1",
        "dialect": "openai",
        "key_env": ["TOGETHER_API_KEY"],
        "json_mode": True,
    },
    "mistral": {
        "base_url": "https://api.mistral.ai/v1",
        "dialect": "openai",
        "key_env": ["MISTRAL_API_KEY"],
        "json_mode": True,
    },
    "xai": {
        "base_url": "https://api.x.ai/v1",
        "dialect": "openai",
        "key_env": ["XAI_API_KEY"],
        "json_mode": True,
    },
    "gemini": {
        "base_url": "https://generativelanguage.googleapis.com/v1beta/openai",
        "dialect": "openai",
        "key_env": ["GEMINI_API_KEY", "GOOGLE_API_KEY"],
        "json_mode": True,
    },
    "custom": {"dialect": "openai"},
}

ALIASES = {
    "nim": "nvidia",
    "nvidia-nim": "nvidia",
    "nvidia_nim": "nvidia",
    "openai-compatible": "custom",
    "openai_compatible": "custom",
    "compatible": "custom",
    "self-hosted": "custom",
    "grok": "xai",
    "google": "gemini",
    "omni": "omniroute",
}

ROLE_ENV = {
    "planner": {
        "provider": "PLANNER_PROVIDER",
        "key": "PLANNER_API_KEY",
        "base": "PLANNER_BASE_URL",
        "model": "PLANNER_MODEL",
        "reasoning": "PLANNER_REASONING",
        "json_mode": "PLANNER_JSON_MODE",
    },
    "policy": {
        "provider": "POLICY_PROVIDER",
        "key": "POLICY_API_KEY",
        "base": "POLICY_BASE_URL",
        "model": "POLICY_MODEL",
        "reasoning": "POLICY_REASONING",
        "json_mode": "POLICY_JSON_MODE",
    },
    "text": {
        "provider": "TEXT_MODEL_PROVIDER",
        "key": "TEXT_MODEL_API_KEY",
        "base": "TEXT_MODEL_BASE_URL",
        "model": "TEXT_MODEL",
        "reasoning": "TEXT_MODEL_REASONING",
        "json_mode": "TEXT_MODEL_JSON_MODE",
    },
}

DEFAULT_TEXT_MODEL = "deepseek-chat"
POLICY_HINT = (
    "Set TYPESAFE_API_KEY to use Jev, or configure your own provider: "
    "POLICY_PROVIDER (openai, anthropic, openrouter, nvidia, omniroute, deepseek, groq, "
    "together, mistral, xai, gemini, custom) plus POLICY_MODEL and POLICY_API_KEY "
    "(or the provider's own variable, e.g. OPENROUTER_API_KEY)."
)


def detect_preset(base_url):
    url = base_url.rstrip("/")
    for name, preset in PROVIDERS.items():
        preset_url = preset.get("base_url", "").rstrip("/")
        if preset_url and (url == preset_url or url.startswith(preset_url + "/")):
            return name, preset
    return None


def reasoning_params(setting, name, dialect):
    """Map the reasoning setting to provider-specific body params; omit anything unverified."""
    if dialect == "anthropic":
        return {}
    setting = (setting or "none").strip().lower()
    if setting in {"none", "off", "disabled"}:
        if name == "deepseek":
            return {"thinking": {"type": "disabled"}}
        if name == "openrouter":
            return {"reasoning": {"enabled": False}}
        if name == "groq":
            # gpt-oss style models always reason; low is the fastest budget available.
            return {"reasoning_effort": "low"}
        return {}
    if setting in {"low", "medium", "high", "minimal"}:
        if name == "openai":
            return {"reasoning_effort": setting}
        if name == "openrouter":
            return {"reasoning": {"effort": setting}}
        if name == "groq":
            return {"reasoning_effort": "low" if setting == "minimal" else setting}
    return {}


def resolve(role):
    """Build one provider config from the environment for the given role."""
    env = ROLE_ENV[role]
    raw = (os.environ.get(env["provider"]) or "").strip()
    base = (os.environ.get(env["base"]) or "").strip()
    key = (os.environ.get(env["key"]) or "").strip()
    name, preset = "", None
    if raw.startswith(("http://", "https://")):
        base, name, preset = (base or raw), "custom", PROVIDERS["custom"]
    elif raw:
        name = ALIASES.get(raw.lower(), raw.lower())
        preset = PROVIDERS.get(name)
        if preset is None:
            known = ", ".join(sorted(PROVIDERS))
            raise ValueError(f"Unknown provider '{raw}' in {env['provider']}. Use: {known}, or a http(s) base URL.")
    if preset and not base:
        base = preset.get("base_url", "")
    elif not preset and base:
        name, preset = detect_preset(base) or ("", None)
    if not base and role == "text":
        name, preset, base = "deepseek", PROVIDERS["deepseek"], PROVIDERS["deepseek"]["base_url"]
    if not base:
        hint = POLICY_HINT if role == "policy" else ""
        raise ValueError(f"{env['base']} is required for a custom {role} provider. {hint}".strip())
    if not key and preset:
        for key_name in preset.get("key_env", []):
            if (os.environ.get(key_name) or "").strip():
                key = os.environ[key_name].strip()
                break
    if not key:
        if preset and preset.get("key_env"):
            extra = f" or one of {', '.join(preset['key_env'])}"
        else:
            extra = f" or set {env['provider']} to a named provider"
        raise ValueError(f"{env['key']} is not set{extra}. No request was sent.")
    model = (os.environ.get(env["model"]) or "").strip()
    if not model and role == "text" and name == "deepseek":
        model = DEFAULT_TEXT_MODEL
    if not model:
        hint = POLICY_HINT if role == "policy" else ""
        raise ValueError(f"{env['model']} is not set; no request was sent. {hint}".strip())
    dialect = "anthropic" if "api.anthropic.com" in base else (preset or {}).get("dialect", "openai")
    json_mode = bool((preset or {}).get("json_mode"))
    flag = (os.environ.get(env["json_mode"]) or "").strip().lower()
    if flag in {"on", "true", "1", "yes"}:
        json_mode = True
    elif flag in {"off", "false", "0", "no"}:
        json_mode = False
    return {
        "name": name or "custom",
        "dialect": dialect,
        "base_url": base,
        "key": key,
        "model": model,
        "reasoning": (os.environ.get(env["reasoning"]) or "none").strip().lower(),
        "json_mode": json_mode,
        "headers": (preset or {}).get("headers", {}),
    }


def _openai_url(base_url):
    url = base_url.rstrip("/")
    return url if url.endswith("/chat/completions") else url + "/chat/completions"


def _anthropic_url(base_url):
    url = base_url.rstrip("/")
    if url.endswith("/messages"):
        return url
    if url.endswith("/v1"):
        url = url[: -len("/v1")]
    return url + "/v1/messages"


def build_request(provider, system, user, max_tokens, omit=()):
    body = {"model": provider["model"]}
    if "max_tokens" in omit:
        body["max_completion_tokens"] = max_tokens  # newer OpenAI-compatible endpoints
    else:
        body["max_tokens"] = max_tokens
    if "reasoning" not in omit:
        body.update(reasoning_params(provider["reasoning"], provider["name"], provider["dialect"]))
    if provider["dialect"] == "anthropic":
        headers = {"x-api-key": provider["key"], "anthropic-version": "2023-06-01"}
        body["system"] = system
        body["messages"] = [{"role": "user", "content": user}]
        return _anthropic_url(provider["base_url"]), headers, body
    if provider["json_mode"] and "response_format" not in omit:
        body["response_format"] = {"type": "json_object"}
    body["messages"] = [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ]
    if provider["headers"]:
        headers = {"Authorization": f"Bearer {provider['key']}", **provider["headers"]}
    else:
        headers = None
    return _openai_url(provider["base_url"]), headers, body


def parse_response(provider, result):
    if provider["dialect"] == "anthropic":
        blocks = result.get("content") or []
        text = "".join(b.get("text", "") for b in blocks if isinstance(b, dict) and b.get("type") == "text")
    else:
        choices = result.get("choices") or []
        message = (choices[0] or {}).get("message", {}) if choices else {}
        text = message.get("content") or ""
        if isinstance(text, list):  # a few gateways return OpenAI content parts
            text = "".join(part.get("text", "") for part in text if isinstance(part, dict))
    meta = {
        "model": result.get("model") or provider["model"],
        "usage": result.get("usage") or {},
        "provider": provider["name"],
    }
    return text, meta


def chat(provider, system, user, max_tokens=1024):
    """Send one chat request; adaptively drop params a strict endpoint rejects.

    OpenAI-compatible providers disagree on response_format, reasoning controls,
    and max_tokens vs max_completion_tokens. Instead of failing, retry without
    the rejected parameter so a model change never breaks a run.
    """
    from . import model  # one shared HTTP seam; tests patch model.post_json

    ladder = (
        (),
        ("response_format",),
        ("response_format", "reasoning"),
        ("response_format", "reasoning", "max_tokens"),
    )
    index = 0
    while True:
        url, headers, body = build_request(provider, system, user, max_tokens, omit=ladder[index])
        if headers is None:
            try:
                result = model.post_json(url, provider["key"], body)
            except RuntimeError as error:
                index = _next_attempt(index, str(error), provider["dialect"])
                if index is None:
                    raise
                continue
        else:
            try:
                result = model.post_json(url, provider["key"], body, headers=headers)
            except RuntimeError as error:
                index = _next_attempt(index, str(error), provider["dialect"])
                if index is None:
                    raise
                continue
        return parse_response(provider, result)


def _next_attempt(index, error, dialect):
    """The next adaptive retry for a rejected parameter, or None to give up."""
    if dialect == "anthropic":
        return None
    lowered = error.lower()
    if index < 1 and "response_format" in lowered:
        return 1
    if index < 2 and ("reasoning" in lowered or "unsupported parameter" in lowered or "unexpected" in lowered):
        return 2
    if index < 3 and ("max_tokens" in lowered or "max_completion_tokens" in lowered):
        return 3
    return None


def extract_json(text):
    """Parse the first JSON object from a model reply, tolerating fences and surrounding prose."""
    stripped = (text or "").strip()
    if not stripped:
        raise ValueError("Model returned an empty response.")
    if stripped.startswith("```"):
        stripped = re.sub(r"^```[a-zA-Z0-9_-]*\s*", "", stripped)
        stripped = re.sub(r"\s*```$", "", stripped).strip()
    try:
        parsed = json.loads(stripped)
    except ValueError:
        parsed = None
    if isinstance(parsed, dict):
        return parsed
    start = stripped.find("{")
    if start >= 0:
        depth = 0
        for position, character in enumerate(stripped[start:], start):
            if character == "{":
                depth += 1
            elif character == "}":
                depth -= 1
                if depth == 0:
                    try:
                        candidate = json.loads(stripped[start : position + 1])
                    except ValueError:
                        break
                    if isinstance(candidate, dict):
                        return candidate
    raise ValueError("Model response contained no JSON object.")
