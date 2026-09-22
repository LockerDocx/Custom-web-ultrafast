# Model providers

Three independent model roles drive the agent, and each one can use a different provider at the same time:

- **Planner** — decomposes the mission into a short checklist of browser steps (optional). `PLANNER_*` variables.
- **Policy** — the fast executor: decides the operation and target on every step. TypeSafe Jev (the original) or any provider below. `POLICY_*` variables.
- **Text helper** — writes the value whenever the policy chooses `TYPE_TEXT`. `TEXT_MODEL_*` variables.

If `TYPESAFE_API_KEY` is set, the policy uses Jev and `POLICY_*` is ignored. Otherwise the policy resolves from `POLICY_PROVIDER` / `POLICY_API_KEY` / `POLICY_BASE_URL` / `POLICY_MODEL`. The text helper always resolves from `TEXT_MODEL_*` variables (its legacy `TEXT_MODEL_BASE_URL` + `TEXT_MODEL` + `TEXT_MODEL_API_KEY` form keeps working).

## Recommended split: fast executor + deep planner

A slow, reasoning-heavy model plans once per task; a fast model executes every step. Two providers at once:

```bash
# Fast executor · GPT-OSS-20B on Groq (free tier, very low latency)
POLICY_PROVIDER=groq
GROQ_API_KEY=gsk_...
POLICY_MODEL=openai/gpt-oss-20b
POLICY_REASONING=low

# Planner + text helper · GLM-5.3 on NVIDIA NIM (free endpoints)
PLANNER_PROVIDER=nvidia
NVIDIA_API_KEY=nvapi-...
PLANNER_MODEL=zai/glm-5.3
TEXT_MODEL_PROVIDER=nvidia
TEXT_MODEL=zai/glm-5.3-flash
TEXT_MODEL_REASONING=none
```

Without `PLANNER_*` configuration the agent keeps the original single-goal loop, so nothing changes for existing setups.

### How planning works

1. The planner is called **once** at task start with the mission and the initial page; it returns `{"steps": [...]}` (1–12 concrete steps).
2. The executor receives the mission, the full checklist (completed steps marked ✓), and the current step — and advances one step per turn.
3. A `DONE` choice marks the current step complete and continues with the next; the last `DONE` ends the run.
4. `BLOCKED` or three consecutive no-change actions trigger a bounded **replan** (max 2 per run): the planner sees the completed steps, the failure reason, and the current page, and returns only the remaining work.
5. The plan is guidance text only — the executor still validates every choice against the observed action space, so no step can invent elements or selectors.

## Presets

| `POLICY_PROVIDER` | Endpoint | Key variable | Notes |
| --- | --- | --- | --- |
| `openai` | `https://api.openai.com/v1` | `OPENAI_API_KEY` | JSON mode on |
| `anthropic` | `https://api.anthropic.com` | `ANTHROPIC_API_KEY` | Native Messages API (`x-api-key` + `anthropic-version`) |
| `openrouter` | `https://openrouter.ai/api/v1` | `OPENROUTER_API_KEY` | Any catalog model, e.g. `anthropic/claude-sonnet-4.5` |
| `nvidia` (alias `nim`) | `https://integrate.api.nvidia.com/v1` | `NVIDIA_API_KEY` | NVIDIA NIM hosted inference |
| `omniroute` | `http://localhost:20128/v1` | `OMNIROUTE_API_KEY` | Self-hosted OmniRoute gateway; override the base URL for remote deployments |
| `deepseek` | `https://api.deepseek.com/v1` | `DEEPSEEK_API_KEY` | Default for the text helper when nothing else is configured |
| `groq` | `https://api.groq.com/openai/v1` | `GROQ_API_KEY` | `openai/gpt-oss-20b` is a fast free executor; `reasoning_effort` is mapped automatically |
| `together` | `https://api.together.xyz/v1` | `TOGETHER_API_KEY` | |
| `mistral` | `https://api.mistral.ai/v1` | `MISTRAL_API_KEY` | |
| `xai` (alias `grok`) | `https://api.x.ai/v1` | `XAI_API_KEY` | |
| `gemini` (alias `google`) | `https://generativelanguage.googleapis.com/v1beta/openai` | `GEMINI_API_KEY` | Gemini's OpenAI-compatible endpoint |
| `custom` | yours, via `POLICY_BASE_URL` | `POLICY_API_KEY` | vLLM, LM Studio, Ollama, LiteLLM, any OpenAI-compatible gateway |
| *(a full URL)* | e.g. `POLICY_PROVIDER=https://gw.internal/v1` | `POLICY_API_KEY` | Same as `custom` |

Aliases: `nim`/`nvidia-nim` → `nvidia`, `grok` → `xai`, `google` → `gemini`, `omni` → `omniroute`, `openai-compatible` → `custom`.

The same table applies to the text helper with `TEXT_MODEL_PROVIDER` and `TEXT_MODEL_*`. When a `*_PROVIDER` is not given, the provider and dialect are inferred from the base URL (`https://api.anthropic.com` selects the Anthropic dialect; anything else is treated as OpenAI-compatible).

## Copy-paste examples

**OpenRouter**

```bash
POLICY_PROVIDER=openrouter
OPENROUTER_API_KEY=sk-or-v1-...
POLICY_MODEL=anthropic/claude-sonnet-4.5
# Optional separate text helper:
TEXT_MODEL_PROVIDER=openrouter
TEXT_MODEL=inception/mercury-2.5
TEXT_MODEL_REASONING=none
```

**NVIDIA NIM**

```bash
POLICY_PROVIDER=nvidia
NVIDIA_API_KEY=nvapi-...
POLICY_MODEL=meta/llama-3.3-70b-instruct
```

**OmniRoute** (self-hosted gateway, default port 20128)

```bash
POLICY_PROVIDER=omniroute
POLICY_BASE_URL=http://localhost:20128/v1   # only if not on the default port/host
OMNIROUTE_API_KEY=sk_omniroute
POLICY_MODEL=cc/claude-sonnet-4.5
```

**OpenAI**

```bash
POLICY_PROVIDER=openai
OPENAI_API_KEY=sk-...
POLICY_MODEL=gpt-4.1
```

**Anthropic**

```bash
POLICY_PROVIDER=anthropic
ANTHROPIC_API_KEY=sk-ant-...
POLICY_MODEL=claude-sonnet-4-5
```

**Your own gateway** (vLLM, LiteLLM, LM Studio, …)

```bash
POLICY_PROVIDER=custom
POLICY_BASE_URL=http://localhost:8000/v1
POLICY_API_KEY=dummy
POLICY_MODEL=Qwen/Qwen2.5-72B-Instruct
```

`POLICY_API_KEY` (or `TEXT_MODEL_API_KEY`) always wins over the preset's own key variable.

## How the generic policy works

The provider policy preserves the loop's core contract: **one request per decision cycle** and **only observed actions can execute**.

1. The same indexed element table, page excerpt, recent actions, and operation catalog that Jev receives are rendered into a single prompt (`POLICY_SYSTEM` in `questions.py`).
2. The model must reply with one JSON object: `{"operation": "CLICK", "target": "3", "confidence": 0.9}`. `SELECT` on a native dropdown uses an observed option index like `"5:2"`.
3. The reply is validated against the action space: an unknown operation, a target from another operation's head, or an invented index is rejected (after one corrective retry) and nothing executes. Model output never becomes selectors, coordinates, or code.
4. Unlike Jev, a generic LLM returns a choice, not a distribution — the inspector shows the chosen target and confidence instead of ranked probabilities.

## Reasoning and JSON mode

- `POLICY_REASONING` / `TEXT_MODEL_REASONING`: `none` (default), `low`, `medium`, `high`.
  - `none` disables thinking where the provider supports it (DeepSeek `thinking: disabled`, OpenRouter `reasoning: {enabled: false}`).
  - Effort levels map to `reasoning_effort` (OpenAI) and `reasoning.effort` (OpenRouter). Unverified combinations are omitted rather than sent.
- `POLICY_JSON_MODE` / `TEXT_MODEL_JSON_MODE`: `on`/`off` override. JSON mode (OpenAI `response_format`) is enabled only for presets that honor it across their catalog; everywhere else the reply is parsed robustly (fences and prose tolerated). Set it to `off` if your endpoint rejects the parameter.

## Troubleshooting

- **`POLICY_API_KEY is not set or one of OPENROUTER_API_KEY...`** — provide the key in either form.
- **`POLICY_MODEL is not set`** — the policy role has no default model; name the exact id your provider expects.
- **HTTP 400 on `response_format`** — set `POLICY_JSON_MODE=off` (or the `TEXT_MODEL_JSON_MODE` equivalent).
- **HTTP 401/403** — the key does not match the provider/base URL combination.
- **OmniRoute 404s** — make sure the base URL includes `/v1` and the OmniRoute gateway is running.
- The text helper still refuses to guess: without a key, `TYPE_TEXT` stops with an error instead of typing an invented value.
