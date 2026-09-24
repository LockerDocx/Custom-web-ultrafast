"""Model discovery: fetch a provider's catalogue and normalize it into a registry.

The registry combines the provider's /models listing (discovery) with inferred
capabilities and the live connectivity probe (firefox.check_providers) as the
runtime validation, per the catalogue-vs-runtime-schema distinction in the spec.
Registry file: artifacts/model-registry.json (refreshed on demand).
"""

import json
import os
import time
from pathlib import Path

from . import parameters, providers

REGISTRY_PATH = Path(os.environ.get("JEV_MODEL_REGISTRY", "artifacts/model-registry.json"))
REGISTRY_TTL_SECONDS = 24 * 3600
DISCOVERABLE = (
    "nvidia", "groq", "openrouter", "deepseek", "together", "mistral", "xai", "gemini", "openai",
    # local runtimes — no API key, listed whenever the server is running
    "ollama", "lmstudio", "llamacpp", "jan",
)

# Non-chat model families commonly listed by catalogues.
_EXCLUDE_MARKERS = (
    "embed", "rerank", "reranker", "guard", "clip", "sdxl", "flux", "stable-diffusion",
    "audio", "whisper", "tts", "stt", "sambert", "canary", "parakeet", "bios",
    "retriever", "nemoretriever", "vista", "esm", "evo", "CAD", "omni",
)
_VISION_MARKERS = ("vl", "vision", "llava", "pixtral", "vila", "image", "multimodal", "gemma-3")
_REASONING_MARKERS = (
    "r1", "reason", "thinking", "qwq", "o1", "o3", "o4", "glm-5", "deepseek-r", "kimi-k",
    "gpt-oss",  # gpt-oss models always reason (see providers.reasoning_params)
)


def provider_key(provider_name):
    """Resolve the API key for a provider without needing a full role config."""
    preset = providers.PROVIDERS.get(provider_name)
    if not preset:
        return None
    for env_name in preset.get("key_env", []):
        value = (os.environ.get(env_name) or "").strip()
        if value:
            return value
    return None


def _is_chat_model(model_id):
    lowered = model_id.lower()
    return not any(marker in lowered for marker in _EXCLUDE_MARKERS)


def _capabilities(model_id):
    lowered = model_id.lower()
    return {
        "text": True,
        "vision": any(marker in lowered for marker in _VISION_MARKERS),
        "reasoning": any(marker in lowered for marker in _REASONING_MARKERS),
        "inferred": True,  # heuristics from the id; the live probe validates at runtime
    }


def _display_name(model_id):
    from .parameters import _display_name as display

    return display(model_id)


def fetch_models(provider_name):
    """Fetch and normalize one provider's catalogue. Raises RuntimeError on failure."""
    preset = providers.PROVIDERS.get(provider_name)
    if not preset or not preset.get("base_url"):
        raise RuntimeError(f"Provider {provider_name} has no catalogue endpoint.")
    if preset.get("local"):
        key = "local"  # localhost servers need no auth
    else:
        key = provider_key(provider_name)
        if not key:
            env_names = ", ".join(preset.get("key_env", [])) or "its API key variable"
            raise RuntimeError(f"No API key for {provider_name} (set {env_names}).")
    from . import model

    url = preset["base_url"].rstrip("/") + "/models"
    try:
        response = model.CLIENT.get(url, headers={"Authorization": f"Bearer {key}"}, timeout=20)
    except Exception as error:  # noqa: BLE001 - surfaced as a readable message
        raise RuntimeError(f"Could not reach {provider_name}: {error}") from None
    if response.status_code == 401 or response.status_code == 403:
        keys_url = preset.get("keys_url", "")
        raise RuntimeError(
            f"{provider_name} rejected the API key (HTTP {response.status_code})."
            f" Generate a fresh key at {keys_url} and update .env."
        )
    if response.is_error:
        raise RuntimeError(f"{provider_name} returned HTTP {response.status_code}.")
    try:
        entries = response.json().get("data", [])
    except ValueError:
        raise RuntimeError(f"{provider_name} returned a malformed catalogue.") from None
    models = []
    seen = set()
    for entry in entries:
        model_id = entry.get("id") if isinstance(entry, dict) else None
        if not model_id or model_id in seen or not _is_chat_model(model_id):
            continue
        seen.add(model_id)
        capabilities = _capabilities(model_id)
        models.append(
            {
                "id": model_id,
                "displayName": _display_name(model_id),
                "provider": provider_name,
                "capabilities": capabilities,
                # spec §4.1/§5: the registry carries each model's validated
                # parameter surface, so the UI never guesses per-model controls.
                "parametersSchema": "jev-v1",
                "parameters": parameters.schema_for_model(provider_name, model_id, capabilities=capabilities)[
                    "parameters"
                ],
            }
        )
    models.sort(key=lambda m: m["displayName"].lower())
    return models


# Opt-in runtime probe (spec §4.1 step 5): one minimal request per model that
# carries every optional parameter; a rejection names the parameter it refuses.
# It spends a few tokens per model, so it only runs when explicitly enabled.
PROBE_SAMPLES = {
    "top_p": 0.9,
    "seed": 42,
    "stop": ["jev-probe-end"],
    "frequency_penalty": 0.1,
    "presence_penalty": 0.1,
    "max_tokens": 16,
}


def probe_enabled():
    return os.environ.get("JEV_PARAM_PROBE", "").strip() in {"1", "true", "on", "yes"}


def probe_parameters(provider_name, model_id, schema):
    """Validate one model's optional parameters against the live endpoint.

    Returns {param: accepted} for the schema's advanced parameters, or None
    when the probe could not run or the error named no parameter (spec §4.2:
    a probe complements the catalogue; it never replaces it).
    """
    from . import providers

    preset = providers.PROVIDERS.get(provider_name) or {}
    if preset.get("local"):
        return None
    key = provider_key(provider_name)
    if not key or not preset.get("base_url"):
        return None
    candidates = [name for name in (schema.get("advanced") or []) if name in PROBE_SAMPLES]
    if not candidates:
        return None
    provider = {
        "name": provider_name,
        "dialect": preset.get("dialect", "openai"),
        "base_url": preset["base_url"],
        "key": key,
        "model": model_id,
        "reasoning": "none",
        "temperature": None,
        "json_mode": False,
        "headers": preset.get("headers", {}),
        "extras": {name: PROBE_SAMPLES[name] for name in candidates},
    }
    from . import model

    # One request, no adaptive retries: a retry would silently drop the very
    # parameter this probe exists to test.
    url, headers, body = providers.build_request(provider, "Reply with the single word pong.", "probe", 16)
    rejected = set()
    try:
        model.post_json(url, key, body, headers=headers)
    except RuntimeError as error:
        lowered = str(error).lower()
        for name in candidates:
            tokens = ("stop_sequences",) if name == "stop" else (name,)
            if any(token in lowered for token in tokens):
                rejected.add(name)
        if not rejected:
            return None  # the failure was not a parameter rejection (auth, quota, ...)
    except ValueError:
        return None
    return {name: name not in rejected for name in candidates}


def discover(refresh=False):
    """The cached registry, refreshed when missing, stale, or forced."""
    registry = None
    if not refresh:
        registry = _load_registry()
        if registry and time.time() - registry.get("fetchedAt", 0) < REGISTRY_TTL_SECONDS:
            return registry
    providers_report = {}
    for name in DISCOVERABLE:
        preset = providers.PROVIDERS.get(name) or {}
        if not preset.get("local") and not provider_key(name):
            continue
        try:
            models = fetch_models(name)
            if probe_enabled():
                for entry in models:
                    schema = {
                        "advanced": [
                            key for key, value in (entry.get("parameters") or {}).items() if value.get("advanced")
                        ]
                    }
                    probed = probe_parameters(name, entry["id"], schema)
                    if probed:
                        entry["probedParams"] = probed
            providers_report[name] = {"ok": True, "models": models}
        except RuntimeError as error:
            providers_report[name] = {"ok": False, "error": str(error)[:300]}
    registry = {"fetchedAt": time.time(), "providers": providers_report}
    _save_registry(registry)
    return registry


def _load_registry():
    try:
        data = json.loads(REGISTRY_PATH.read_text())
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) and "providers" in data else None


def _save_registry(registry):
    REGISTRY_PATH.parent.mkdir(parents=True, exist_ok=True)
    REGISTRY_PATH.write_text(json.dumps(registry, indent=2))
