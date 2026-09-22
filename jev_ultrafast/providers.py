"""Multi-provider LLM engine for ultrafast browser automation.

Supports:
- OpenRouter (https://openrouter.ai)
- OmniRoute (http://localhost:20128 or custom gateway)
- NVIDIA NIM (https://integrate.api.nvidia.com)
- Anthropic Claude (https://api.anthropic.com)
- OpenAI (https://api.openai.com)
- TypeSafe Jev (https://api.typesafe.ai)
"""

import json
import os
import re
import time
from typing import Any, Dict, List, Optional, Tuple

import httpx

from .questions import NEXT_ACTION

# Reusable HTTP client with HTTP/2 and standard timeouts
CLIENT = httpx.Client(http2=True, timeout=25)

PROVIDER_DEFAULTS = {
    "openrouter": {
        "base_url": "https://openrouter.ai/api/v1",
        "default_model": "deepseek/deepseek-chat",
        "env_keys": ["OPENROUTER_API_KEY", "LLM_API_KEY"],
        "api_type": "openai",
    },
    "omniroute": {
        "base_url": "http://localhost:20128/v1",
        "default_model": "gpt-4o-mini",
        "env_keys": ["OMNIROUTE_API_KEY", "LLM_API_KEY"],
        "api_type": "openai",
    },
    "nvidia": {
        "base_url": "https://integrate.api.nvidia.com/v1",
        "default_model": "meta/llama-3.1-70b-instruct",
        "env_keys": ["NVIDIA_API_KEY", "NVIDIA_NIM_API_KEY", "LLM_API_KEY"],
        "api_type": "openai",
    },
    "anthropic": {
        "base_url": "https://api.anthropic.com/v1",
        "default_model": "claude-3-5-haiku-20241022",
        "env_keys": ["ANTHROPIC_API_KEY", "LLM_API_KEY"],
        "api_type": "anthropic",
    },
    "openai": {
        "base_url": "https://api.openai.com/v1",
        "default_model": "gpt-4o-mini",
        "env_keys": ["OPENAI_API_KEY", "LLM_API_KEY"],
        "api_type": "openai",
    },
    "typesafe": {
        "base_url": "https://api.typesafe.ai/v1",
        "default_model": "jev-latest",
        "env_keys": ["TYPESAFE_API_KEY"],
        "api_type": "typesafe",
    },
}


def normalize_provider(name: Optional[str]) -> str:
    if not name:
        return ""
    clean = name.strip().lower().replace("_", "").replace("-", "")
    mapping = {
        "openrouter": "openrouter",
        "omniroute": "omniroute",
        "nvidia": "nvidia",
        "nvidianim": "nvidia",
        "nim": "nvidia",
        "anthropic": "anthropic",
        "claude": "anthropic",
        "openai": "openai",
        "typesafe": "typesafe",
        "jev": "typesafe",
    }
    return mapping.get(clean, clean)


def detect_provider() -> str:
    """Detect the active provider from environment variables."""
    explicit = os.environ.get("LLM_PROVIDER")
    if explicit:
        return normalize_provider(explicit)

    # Check provider-specific keys in priority order
    for prov, info in PROVIDER_DEFAULTS.items():
        if prov == "typesafe":
            continue
        for key_name in info["env_keys"]:
            if key_name != "LLM_API_KEY" and os.environ.get(key_name):
                return prov

    if os.environ.get("TYPESAFE_API_KEY"):
        return "typesafe"

    if os.environ.get("LLM_API_KEY"):
        return "openrouter"

    return "openrouter"


def get_provider_config(provider_name: Optional[str] = None) -> Dict[str, Any]:
    """Retrieve full configuration (base_url, api_key, model, api_type) for a provider."""
    provider = normalize_provider(provider_name) or detect_provider()
    defaults = PROVIDER_DEFAULTS.get(provider, PROVIDER_DEFAULTS["openrouter"])

    # Resolve API Key
    api_key = ""
    for env_key in defaults["env_keys"]:
        val = os.environ.get(env_key)
        if val:
            api_key = val.strip()
            break

    # Resolve Base URL
    base_url = (
        os.environ.get(f"{provider.upper()}_BASE_URL")
        or os.environ.get("LLM_BASE_URL")
        or defaults["base_url"]
    ).rstrip("/")

    # Resolve Model
    model = (
        os.environ.get(f"{provider.upper()}_MODEL")
        or os.environ.get("LLM_MODEL")
        or defaults["default_model"]
    )

    return {
        "provider": provider,
        "api_type": defaults["api_type"],
        "base_url": base_url,
        "api_key": api_key,
        "model": model,
    }


def extract_json(raw_text: str) -> Dict[str, Any]:
    """Extract and parse JSON object from raw LLM text, handling markdown blocks and preamble."""
    text = raw_text.strip()
    if text.startswith("```"):
        lines = text.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].startswith("```"):
            lines = lines[:-1]
        text = "\n".join(lines).strip()

    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    # Find enclosing braces
    start = text.find("{")
    end = text.rfind("}")
    if start != -1 and end != -1 and end > start:
        snippet = text[start : end + 1]
        try:
            return json.loads(snippet)
        except json.JSONDecodeError:
            # Clean trailing commas
            cleaned = re.sub(r",\s*([\]}])", r"\1", snippet)
            return json.loads(cleaned)

    raise ValueError(f"Could not extract JSON from model output: {raw_text[:200]}")


SYSTEM_PROMPT = f"""You are an ultrafast browser automation agent.
Your mission is to accomplish the user's goal step-by-step on the current webpage.

RULES:
{NEXT_ACTION}

You must select exactly ONE operation to execute next:
- CLICK: Click a button, link, tab, checkbox, radio, or menu option.
- TYPE_TEXT: Type text into an input field or combobox. Supply the exact text.
- SELECT: Select an option from an HTML dropdown.
- SCROLL_DOWN: Scroll down to reveal more content.
- SCROLL_UP: Scroll up to review previous content.
- WAIT: Wait briefly for dynamic elements or search results to load.
- DONE: The goal is completely and visibly fulfilled on the page.
- BLOCKED: No supported action can make progress toward the goal.

OUTPUT FORMAT:
You MUST output ONLY a valid JSON object with these keys:
{{
  "thought": "1-sentence reason explaining why this action advances the goal",
  "operation": "CLICK" | "TYPE_TEXT" | "SELECT" | "SCROLL_DOWN" | "SCROLL_UP" | "WAIT" | "DONE" | "BLOCKED",
  "target": "Element index, e.g. '1', '2', '4:1', or control name like 'WAIT'",
  "text": "Exact text to type if operation is TYPE_TEXT; otherwise null"
}}
"""


def format_prompt(
    elements: List[Dict],
    targets: Dict,
    controls: Dict,
    page: Dict,
    goal: str,
    history: List[Dict],
) -> str:
    """Format observation and action space into a compact prompt."""
    element_lines = []
    for el in elements:
        idx = el["index"]
        role = el.get("role", "element")
        label = el.get("label", "").strip()
        ops = "/".join(el.get("operations", []))
        val = el.get("value")
        val_part = f" · value: {json.dumps(val)}" if val else ""
        opts = el.get("options")
        opts_part = ""
        if opts:
            sample_opts = [f"[{o['index']}] {o['label'].split(' → ')[-1]}" for o in opts[:8]]
            opts_part = f" · options: {', '.join(sample_opts)}"
        element_lines.append(f"[{idx}] {role} '{label}' ({ops}){val_part}{opts_part}")

    control_lines = []
    for op_name, ctrl in controls.items():
        control_lines.append(f"[{op_name}] {ctrl.get('label', op_name)}")
    control_lines.append("[DONE] Every requirement is visibly satisfied.")
    control_lines.append("[BLOCKED] No supported operation can make progress.")

    history_lines = []
    for h in history[-6:]:
        act = h.get("action", "")
        txt = f" (typed: '{h['text']}')" if h.get("text") else ""
        history_lines.append(f"- Step {h.get('step', '?')}: {act}{txt}")

    hist_str = "\n".join(history_lines) if history_lines else "None (first step)"
    elem_str = "\n".join(element_lines) if element_lines else "No interactive elements detected."
    ctrl_str = "\n".join(control_lines)

    text_excerpt = (page.get("text") or "")[:3000].strip()

    return f"""USER GOAL:
{goal}

CURRENT PAGE:
Title: {page.get('title', '')}
URL: {page.get('url', '')}

PAGE TEXT EXCERPT:
{text_excerpt}

RECENT ACTION HISTORY:
{hist_str}

INTERACTIVE ELEMENTS ON PAGE:
{elem_str}

GLOBAL CONTROLS & TERMINATION:
{ctrl_str}

Pick the single next action. Output JSON only."""


def post_openai_compatible(
    url: str,
    key: str,
    model: str,
    messages: List[Dict[str, str]],
    custom_headers: Optional[Dict[str, str]] = None,
    temperature: float = 0.1,
    max_tokens: int = 512,
) -> Tuple[Dict[str, Any], int]:
    """Call an OpenAI-compatible /chat/completions endpoint."""
    headers = {"Content-Type": "application/json"}
    if key:
        headers["Authorization"] = f"Bearer {key}"
    if custom_headers:
        headers.update(custom_headers)

    body = {
        "model": model,
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
        "response_format": {"type": "json_object"},
    }

    started = time.perf_counter()
    for attempt in range(3):
        try:
            response = CLIENT.post(url, json=body, headers=headers)
        except httpx.HTTPError as err:
            if attempt == 2:
                raise RuntimeError(f"Connection to LLM provider failed: {err}") from None
            time.sleep(0.5 * 2**attempt)
            continue

        if response.status_code in {429, 502, 503, 529} and attempt < 2:
            time.sleep(0.5 * 2**attempt)
            continue

        # If provider doesn't support response_format json_object, retry without it
        if response.status_code == 400 and "response_format" in response.text and "response_format" in body:
            del body["response_format"]
            continue

        if response.is_error:
            raise RuntimeError(f"LLM provider error (HTTP {response.status_code}): {response.text[:300]}")

        data = response.json()
        latency_ms = round((time.perf_counter() - started) * 1000)
        return data, latency_ms

    raise RuntimeError("LLM provider unavailable after retries")


def post_anthropic(
    url: str,
    key: str,
    model: str,
    system: str,
    user_prompt: str,
    temperature: float = 0.1,
    max_tokens: int = 512,
) -> Tuple[Dict[str, Any], int]:
    """Call the Anthropic /messages endpoint."""
    headers = {
        "x-api-key": key,
        "anthropic-version": "2023-06-01",
        "content-type": "application/json",
    }
    body = {
        "model": model,
        "system": system,
        "messages": [{"role": "user", "content": user_prompt}],
        "temperature": temperature,
        "max_tokens": max_tokens,
    }

    started = time.perf_counter()
    for attempt in range(3):
        try:
            response = CLIENT.post(url, json=body, headers=headers)
        except httpx.HTTPError as err:
            if attempt == 2:
                raise RuntimeError(f"Connection to Anthropic failed: {err}") from None
            time.sleep(0.5 * 2**attempt)
            continue

        if response.status_code in {429, 503, 529} and attempt < 2:
            time.sleep(0.5 * 2**attempt)
            continue

        if response.is_error:
            raise RuntimeError(f"Anthropic error (HTTP {response.status_code}): {response.text[:300]}")

        data = response.json()
        latency_ms = round((time.perf_counter() - started) * 1000)
        return data, latency_ms

    raise RuntimeError("Anthropic unavailable after retries")


def resolve_action_choice(
    parsed: Dict[str, Any],
    targets: Dict[str, Dict[str, Any]],
    controls: Dict[str, Any],
    actions: List[Dict[str, Any]],
) -> Tuple[str, str, Optional[str], Optional[str]]:
    """Map LLM-parsed operation and target to a verified action choice ID.

    Returns:
        (choice_id, operation, target_index, text_to_type)
    """
    op = str(parsed.get("operation", "")).upper().strip()
    raw_target = str(parsed.get("target", "")).strip("[] \t\n")
    text = parsed.get("text")
    if text is not None:
        text = str(text)

    # Termination and control operations
    if op == "DONE" or raw_target.upper() == "DONE":
        return "DONE", "DONE", None, None
    if op == "BLOCKED" or raw_target.upper() == "BLOCKED":
        return "BLOCKED", "BLOCKED", None, None
    if op == "WAIT" or raw_target.upper() == "WAIT":
        return controls.get("WAIT", {}).get("id", "wait"), "WAIT", None, None
    if op in ("SCROLL_DOWN", "SCROLL_UP") or raw_target.upper() in ("SCROLL_DOWN", "SCROLL_UP"):
        key = "SCROLL_DOWN" if "DOWN" in (op + raw_target).upper() else "SCROLL_UP"
        return controls.get(key, {}).get("id", key.lower()), key, None, None

    # Normal element operations: CLICK, TYPE_TEXT, SELECT
    valid_ops = {"CLICK", "TYPE_TEXT", "SELECT"}
    if op not in valid_ops:
        # Infer operation if target is present
        if text:
            op = "TYPE_TEXT"
        elif ":" in raw_target:
            op = "SELECT"
        else:
            op = "CLICK"

    # Match target by element index
    target_group = targets.get(op, {})
    if raw_target in target_group:
        return target_group[raw_target]["id"], op, raw_target, text

    # Try matching if target index is in another operation group
    for other_op, group in targets.items():
        if raw_target in group:
            return group[raw_target]["id"], other_op, raw_target, text

    # Check if raw_target matches an action ID directly (e.g. 'e1', 'e2')
    for a in actions:
        if a["id"].lower() == raw_target.lower():
            # Find which index/operation it belongs to
            for top, group in targets.items():
                for idx, taction in group.items():
                    if taction["id"] == a["id"]:
                        return a["id"], top, idx, text
            return a["id"], op, raw_target, text

    # Check if target contains digit (e.g., "[1]" or "1.")
    digits = re.findall(r"\d+(?::\d+)?", raw_target)
    if digits:
        candidate = digits[0]
        if candidate in target_group:
            return target_group[candidate]["id"], op, candidate, text
        for other_op, group in targets.items():
            if candidate in group:
                return group[candidate]["id"], other_op, candidate, text

    # Fallback to first available target if none matched
    if target_group:
        first_idx = next(iter(target_group))
        return target_group[first_idx]["id"], op, first_idx, text

    # If all else fails, wait
    return controls.get("WAIT", {}).get("id", "wait"), "WAIT", None, None


def choose_llm(
    state: Dict[str, Any],
    goal: str,
    history: List[Dict[str, Any]],
    provider_config: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Execute action selection using an LLM provider (OpenRouter, OmniRoute, NVIDIA NIM, Anthropic, OpenAI)."""
    from .model import action_space

    config = provider_config or get_provider_config()
    provider = config["provider"]
    api_type = config["api_type"]
    base_url = config["base_url"]
    api_key = config["api_key"]
    model = config["model"]

    elements, targets, controls = action_space(state["actions"])
    user_prompt = format_prompt(elements, targets, controls, state, goal, history)

    custom_headers = {}
    if provider == "openrouter":
        custom_headers = {
            "HTTP-Referer": "https://github.com/LockerDocx/Custom-web-ultrafast",
            "X-Title": "Custom-web-ultrafast",
        }

    if api_type == "anthropic":
        url = f"{base_url}/messages"
        resp, latency_ms = post_anthropic(
            url=url,
            key=api_key,
            model=model,
            system=SYSTEM_PROMPT,
            user_prompt=user_prompt,
        )
        content = resp["content"][0]["text"]
        usage = resp.get("usage", {})
    else:
        url = f"{base_url}/chat/completions"
        messages = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt},
        ]
        resp, latency_ms = post_openai_compatible(
            url=url,
            key=api_key,
            model=model,
            messages=messages,
            custom_headers=custom_headers,
        )
        content = resp["choices"][0]["message"]["content"]
        usage = resp.get("usage", {})

    parsed = extract_json(content)
    choice, operation, target, text = resolve_action_choice(
        parsed=parsed,
        targets=targets,
        controls=controls,
        actions=state["actions"],
    )

    thought = parsed.get("thought", "")

    return {
        "choice": choice,
        "operation": operation,
        "target": target,
        "text": text,
        "thought": thought,
        "confidence": 1.0,
        "probabilities": {choice: 1.0},
        "operation_probabilities": {operation: 1.0},
        "target_probabilities": {target: 1.0} if target else {},
        "target_confidence": 1.0 if target else None,
        "raw_answers": parsed,
        "model": f"{provider}/{model}",
        "usage": usage,
        "latency_ms": latency_ms,
        "request": {
            "provider": provider,
            "model": model,
            "goal": goal,
        },
    }
