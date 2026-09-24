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

from . import providers, schemas

REGISTRY_PATH = Path(os.environ.get("JEV_MODEL_REGISTRY", "artifacts/model-registry.json"))
REGISTRY_TTL_SECONDS = 24 * 3600
REGISTRY_VERSION = 2
# Catalogues queried on discovery. Every provider here needs its API key; local
# LLM runtimes were removed on purpose (the browser needs the internet anyway).
DISCOVERABLE = (
    "nvidia", "groq", "openrouter", "deepseek", "together", "mistral", "xai", "gemini", "openai",
)

# Non-chat model families commonly listed by catalogues.
_EXCLUDE_MARKERS = (
    "embed", "rerank", "reranker", "guard", "clip", "sdxl", "flux", "stable-diffusion",
    "audio", "whisper", "tts", "stt", "sambert", "canary", "parakeet", "bios",
    "retriever", "nemoretriever", "vista", "esm", "evo", "CAD", "omni",
)
_VISION_MARKERS = ("vl", "vision", "llava", "pixtral", "vila", "image", "multimodal", "gemma-3")
_NO_TOOLS_MARKERS = ("instruct-base", "base", "text-davinci")
_CODING_MARKERS = ("code", "coder", "devstral", "codestral", "starcoder", "qwen3-coder")
_REASONING_MARKERS = ("r1", "reason", "thinking", "qwq", "o1", "o3", "o4", "glm-5", "deepseek-r", "kimi-k")


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


def _capabilities(model_id, entry=None):
    """Normalized capabilities for one catalogue entry (spec §4.3).

    Whatever the provider states wins; the rest is inferred from the id and
    flagged as such, because only the runtime probe can confirm it.
    """
    lowered = model_id.lower()
    capabilities = {
        "text": True,
        "vision": any(marker in lowered for marker in _VISION_MARKERS),
        "reasoning": any(marker in lowered for marker in _REASONING_MARKERS),
        "tool_calling": not any(marker in lowered for marker in _NO_TOOLS_MARKERS),
        "coding": any(marker in lowered for marker in _CODING_MARKERS),
        "inferred": True,  # heuristics from the id; the live probe validates at runtime
    }
    stated = {}
    if isinstance(entry, dict):
        # NVIDIA NIM and a few gateways ship metadata next to the id; when they
        # do, it replaces the guess instead of competing with it.
        for source_key, target in (
            ("modalities", None), ("capabilities", None), ("supported_features", None),
        ):
            value = entry.get(source_key)
            if isinstance(value, dict):
                stated.update({str(k).lower(): bool(v) for k, v in value.items()})
            elif isinstance(value, list):
                stated.update({str(item).lower(): True for item in value})
        for name, aliases in (
            ("vision", ("vision", "image", "multimodal")),
            ("reasoning", ("reasoning", "thinking")),
            ("tool_calling", ("tools", "tool_calling", "function_calling")),
        ):
            for alias in aliases:
                if alias in stated:
                    capabilities[name] = stated[alias]
                    capabilities["inferred"] = False
    capabilities["agentic"] = capabilities["tool_calling"] and capabilities["text"]
    return capabilities


def _display_name(model_id):
    from .parameters import _display_name as display

    return display(model_id)


def fetch_models(provider_name):
    """Fetch and normalize one provider's catalogue. Raises RuntimeError on failure."""
    preset = providers.PROVIDERS.get(provider_name)
    if not preset or not preset.get("base_url"):
        raise RuntimeError(f"Provider {provider_name} has no catalogue endpoint.")
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
    discovered_at = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    for entry in entries:
        model_id = entry.get("id") if isinstance(entry, dict) else None
        if not model_id or model_id in seen or not _is_chat_model(model_id):
            continue
        seen.add(model_id)
        capabilities = _capabilities(model_id, entry)
        dialect = preset.get("dialect", "openai")
        schema = schemas.schema_for(provider_name, model_id, capabilities, dialect=dialect)
        models.append(
            {
                "id": model_id,
                "displayName": _display_name(model_id),
                "provider": provider_name,
                "endpoint": preset["base_url"],
                "capabilities": capabilities,
                # the parameter surface this model exposes, per the family rules
                "parametersSchema": schema["schemaId"],
                "parameters": sorted(schema["parameters"]),
                "source": f"{preset['base_url'].rstrip('/')}/models",
                "discoveredAt": discovered_at,
            }
        )
    models.sort(key=lambda m: m["displayName"].lower())
    return models


def discover(refresh=False):
    """The cached registry, refreshed when missing, stale, or forced."""
    registry = None
    if not refresh:
        registry = _load_registry()
        fresh = registry and time.time() - registry.get("fetchedAt", 0) < REGISTRY_TTL_SECONDS
        if fresh and registry.get("version") == REGISTRY_VERSION:
            return registry
    providers_report = {}
    for name in DISCOVERABLE:
        if not provider_key(name):
            continue  # no key for that provider: nothing to ask
        try:
            providers_report[name] = {"ok": True, "models": fetch_models(name)}
        except RuntimeError as error:
            providers_report[name] = {"ok": False, "error": str(error)[:300]}
    registry = {
        "version": REGISTRY_VERSION,
        "fetchedAt": time.time(),
        "providers": providers_report,
    }
    _save_registry(registry)
    return registry


# Values used to ask an endpoint "do you accept this?" — deliberately harmless.
PROBE_VALUES = {
    "temperature": 0.5,
    "top_p": 0.9,
    "seed": 7,
    "stop": ["</probe>"],
    "frequency_penalty": 0.1,
    "presence_penalty": 0.1,
    "reasoning": "low",
}


def probe_model(provider_name, model_id, refresh=True):
    """Ask the live endpoint which parameters it really accepts (spec §4.1, step 5).

    One tiny request carrying every candidate parameter; each rejection names a
    parameter, which is dropped and recorded before retrying. The resulting
    evidence is what makes the sidebar hide controls the model does not have —
    a catalogue that changes under us can no longer silently break inference.
    """
    provider_name = (provider_name or "").strip().lower()
    model_id = (model_id or "").strip()
    preset = providers.PROVIDERS.get(provider_name)
    if not preset or not model_id:
        raise RuntimeError(f"Cannot probe {provider_name or '?'}/{model_id or '?'}: unknown model.")
    key = provider_key(provider_name) or (
        "local" if providers._is_loopback_url(preset.get("base_url", "")) else ""
    )
    if not key:
        env_names = ", ".join(preset.get("key_env", [])) or "its API key variable"
        raise RuntimeError(f"No API key for {provider_name} (set {env_names}).")
    if refresh:
        schemas.forget(provider_name, model_id)
    dialect = preset.get("dialect", "openai")
    schema = providers.model_schema(provider_name, model_id, dialect)
    params = {name: value for name, value in PROBE_VALUES.items() if name in schema["parameters"]}
    provider = {
        "name": provider_name,
        "dialect": dialect,
        "base_url": preset.get("base_url", ""),
        "key": key,
        "model": model_id,
        "reasoning": params.get("reasoning", "none"),
        "temperature": params.get("temperature"),
        "params": params,
        "schema": schema,
        "json_mode": False,
        "headers": preset.get("headers", {}),
    }
    error = None
    try:
        providers.chat(provider, "Answer with the single word OK.", "Say OK.", max_tokens=16)
    except RuntimeError as failure:  # a dead key or a missing model, not a parameter verdict
        error = str(failure)[:300]
    evidence = schemas.runtime_evidence(provider_name, model_id)
    return {
        "provider": provider_name,
        "model": model_id,
        "schemaId": schema["schemaId"],
        "probed": sorted(params),
        "verified": evidence.get("verified", []),
        "unsupported": evidence.get("unsupported", []),
        "checkedAt": evidence.get("checkedAt"),
        "error": error,
    }


def _load_registry():
    try:
        data = json.loads(REGISTRY_PATH.read_text())
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) and "providers" in data else None


def _save_registry(registry):
    REGISTRY_PATH.parent.mkdir(parents=True, exist_ok=True)
    REGISTRY_PATH.write_text(json.dumps(registry, indent=2))
