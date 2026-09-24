# Model discovery and per-model parameters (MVP-1)

> Spec sections 4 (NVIDIA NIM model discovery) and 5 (dynamic parameter system).

NVIDIA NIM lists ~100 models and the list changes constantly. Kimi takes
`reasoning_effort: low|high|max`, GLM toggles thinking through
`chat_template_kwargs`, DeepSeek-R1 always reasons, an Anthropic endpoint takes
none of them, and a plain Llama takes the usual OpenAI set. So the product rule
is the spec's: **models are data, not branches in the code.**

Three layers produce the controls you see in the sidebar, and the parameters
that reach the wire:

```text
1. catalogue      GET {base_url}/models            → discovery.py  → artifacts/model-registry.json
2. family rules   schemas.RULES (declarative)      → schemas.py
3. runtime truth  what the endpoint accepted/rejected → artifacts/model-runtime.json
                                   ↓
                     schemas.schema_for(provider, model)
                                   ↓
              sidebar widgets  +  validation  +  request body
```

## 1. Discovery → registry

`jev-firefox` refreshes the catalogue on demand (sidebar → **Refresh
catalogue**) and caches it for 24 h in `artifacts/model-registry.json`. Each
entry is normalized as in spec §4.3:

```json
{
  "id": "moonshotai/kimi-k3",
  "displayName": "Kimi K3",
  "provider": "nvidia",
  "endpoint": "https://integrate.api.nvidia.com/v1",
  "capabilities": { "text": true, "vision": false, "reasoning": true,
                    "tool_calling": true, "coding": false, "agentic": true,
                    "inferred": true },
  "parametersSchema": "kimi-v1",
  "parameters": ["max_tokens", "reasoning", "seed", "stream", "temperature"],
  "source": "https://integrate.api.nvidia.com/v1/models",
  "discoveredAt": "2026-09-24T09:40:11Z"
}
```

`capabilities.inferred` is `true` when the flags come from the model id rather
than from provider metadata — i.e. a hint, not a promise. The runtime probe is
what turns hints into facts.

## 2. Family rules: the parameter vocabulary

`schemas.BASE_PARAMETERS` is the normalized vocabulary (spec §5.2):

| Parameter | Type | Tier | Notes |
|---|---|---|---|
| `reasoning` | enum | simple | Ladder and wiring depend on the family |
| `temperature` | number 0–2 | simple | |
| `max_tokens` | integer | simple | Lowers the loop's own budget, floor 64 |
| `stream` | boolean | simple | |
| `top_p` | number 0–1 | advanced | |
| `seed` | integer | advanced | |
| `stop` | array (≤4) | advanced | |
| `frequency_penalty` | number -2–2 | advanced | |
| `presence_penalty` | number -2–2 | advanced | |

`schemas.RULES` is an ordered list of declarative rules matched on dialect,
provider and/or a regex over the model id. A rule can `keep`, `drop` or
`override` parameters and declare how `reasoning` reaches the wire:

| Family | Schema id | Reasoning wiring | Notable |
|---|---|---|---|
| Kimi K-series | `kimi-v1` | `reasoning_effort: low/high/max` | no `top_p`, no penalties, no `stop` |
| GLM | `glm-v1` | `chat_template_kwargs.thinking` | full OpenAI set |
| gpt-oss | `gpt-oss-v1` | `reasoning_effort: low/medium/high` | |
| Nemotron / Qwen3 | `nemotron-v1`, `qwen-v1` | `chat_template_kwargs.thinking` | |
| DeepSeek-R1 | `deepseek-r-v1` | always on — no control | |
| DeepSeek API | `deepseek-v1` | `thinking: {type}` | |
| OpenRouter | `openrouter-v1` | `reasoning: {effort}` | off by default so it is not billed |
| Anthropic | `anthropic-v1` | none | only temperature/top_p/max_tokens/stop/stream |
| Local runtimes | `local-v1` | inferred | no penalties |
| Anything else | `openai-v1` | `reasoning_effort` when the model reasons | |

Adding a family is a dict in `RULES`, never an `if`.

A preset asks for intent, not for fields: "Deep" wants `reasoning=high`, and if
a model's ladder is `low/high/max` the request is projected onto the nearest
supported level (ties favour the higher budget) — see
`parameters.supported_subset`.

## 3. Runtime truth

The catalogue is for discovery, not for deciding every request parameter
(spec §4.2). Two mechanisms keep the schema honest:

- **Adaptive requests.** When an endpoint rejects a parameter, the request
  layer drops it, retries, and records the rejection in
  `artifacts/model-runtime.json`. The control then disappears from the sidebar
  for that model. Parameters that survived a successful call are marked
  `verified ✓`.
- **The probe** (spec §4.1, step 5). The **Probe model** button sends one tiny
  request carrying every candidate parameter and reports what the model
  accepted:

```bash
python -c "from jev_ultrafast import discovery, firefox; \
firefox.load_environment(); print(discovery.probe_model('nvidia', 'moonshotai/kimi-k3'))"
```

Switching a role's model prunes values the new model cannot take (moving from
GLM to Kimi drops `top_p`), and the sidebar says so.

## 4. Environment variables

Every parameter has one variable per role, `<PREFIX>_<PARAMETER>`, with
prefixes `PLANNER`, `POLICY` and `TEXT_MODEL`:

```bash
POLICY_REASONING=low          # none | low | medium | high (| max on Kimi)
POLICY_TEMPERATURE=0.2
POLICY_TOP_P=0.9
POLICY_MAX_TOKENS=512
POLICY_SEED=7
POLICY_STOP=END,###           # comma separated, up to 4
POLICY_FREQUENCY_PENALTY=0.1
POLICY_PRESENCE_PENALTY=0.1
```

The sidebar writes the same values to `artifacts/model-config.json` and
re-applies them over `.env` at startup, so the UI and the file agree. A value
the selected model does not support is refused with the reason
(`top_p is not supported by moonshotai/kimi-k3`) instead of being sent and
failing mid-run.
