<img src="docs/banner.svg" alt="Jev Agent — open-source Firefox AI agent" width="100%" />

# Jev Agent — the open-source Firefox AI agent

**A free AI agent that drives your own Firefox tab.** You write a goal in the sidebar — *"search Google Flights for Zürich to London next Sunday, one adult"* — and it navigates, clicks, types and scrolls for you, showing the plan and every action as it happens. It runs on your machine, uses **one free API key**, and needs no account, no subscription and no cloud dashboard.

[![CI](https://github.com/LockerDocx/firefox-ai-agent/actions/workflows/ci.yml/badge.svg)](https://github.com/LockerDocx/firefox-ai-agent/actions/workflows/ci.yml)
![Python 3.11+](https://img.shields.io/badge/python-3.11%2B-blue)
![Firefox 109+](https://img.shields.io/badge/firefox-109%2B-orange)
![Platforms](https://img.shields.io/badge/platforms-Windows%20%7C%20Linux%20%7C%20openSUSE%20%7C%20macOS-lightgrey)
[![License: MIT](https://img.shields.io/badge/license-MIT-green)](LICENSE)

> 🇪🇸 **¿Prefieres español?** Manual paso a paso, sin consola: **[EMPEZAR-AQUI.md](EMPEZAR-AQUI.md)** ·
> Guía detallada sistema por sistema: **[docs/setup-por-sistema.md](docs/setup-por-sistema.md)**.

<a href="docs/demo.gif"><img src="docs/demo.gif" alt="A real Google Flights search driven by the agent, with generated city names and dynamic click targets" width="100%" /></a>

---

## Quick start

Five steps, about ten minutes, no commands to type.

| Step | What you do |
| --- | --- |
| **1 · Download** | **[Download the ZIP](https://github.com/LockerDocx/firefox-ai-agent/archive/refs/heads/main.zip)** (or the `source.zip` from [Releases](https://github.com/LockerDocx/firefox-ai-agent/releases/latest)) and extract it somewhere you will keep it. |
| **2 · Free key** | Get one at **[console.groq.com/keys](https://console.groq.com/keys)** (2 minutes, free, Google login works). It is the only thing the agent needs. |
| **3 · One double-click** | Double-click the starter for your system — `start-host.bat` (Windows), `start-host.command` (macOS), `start-host.sh` (Linux). It prepares everything (~1 min) and **registers the agent with Firefox**. From then on this double-click is not needed again. |
| **4 · Load the add-on** | Firefox → `about:debugging` → *This Firefox* → **Load Temporary Add-on…** → pick **`jev-agent-firefox.xpi`** from [Releases](https://github.com/LockerDocx/firefox-ai-agent/releases/latest) (or `extension/manifest.json`). |
| **5 · Paste the key** | Open the **Jev sidebar** (toolbar button), paste the key into the card, press **Save**. Then press **Test setup**: every model turns green with its latency. |

Write a goal, press **Run**, and watch your Firefox work. Full point-and-click walkthrough: **[docs/getting-started-gui.md](docs/getting-started-gui.md)**.

### Python, per system

The starter looks for a compatible interpreter itself (`python3.13` → `python3.12` → `python3.11` → `python3`) and, if none is new enough, it prints the exact command for your distribution. To get ahead of it:

| System | Install Python 3.11+ |
| --- | --- |
| **openSUSE / SUSE (Leap 15.6)** | `sudo zypper install python312 python312-pip` — ⚠️ Leap's own `python3` is 3.6 (the YaST one), so this install is required |
| **openSUSE Tumbleweed** | nothing — its `python3` is already 3.13 |
| **Ubuntu · Debian · Mint** | `sudo apt update && sudo apt install python3 python3-pip python3-venv` (on Ubuntu 22.04/Mint 21, get 3.12 from the deadsnakes PPA) |
| **Fedora** | `sudo dnf install python3 python3-pip` |
| **RHEL · Rocky · Alma 9** | `sudo dnf install python3.11 python3.11-pip` (their `python3` is 3.9) |
| **Arch · Manjaro** | `sudo pacman -S python` |
| **Windows** | the [python.org](https://www.python.org/downloads/) installer, ticking **Add python.exe to PATH**. If typing `python` opens the Microsoft Store, that is the Store stub — install the real one. |
| **macOS** | `brew install python@3.12`, or the python.org installer |

SUSE package names carry no dot (`python312`, never `python3.12`). Details, per-system terminal tricks and troubleshooting: **[docs/setup-por-sistema.md](docs/setup-por-sistema.md)**.

---

## What it does

**Agent loop with a plan.** A planner model writes a short checklist for the mission; a fast executor model picks one action per turn. The sidebar shows the checklist ticking ✓, the live page, the executed actions, and a **Stop** button.

**Dynamic action space, not selectors.** Every observation produces an indexed table of the controls actually on screen (`[7] button · Search`) and the model chooses an operation and one element from it. It never writes CSS selectors or code, so a wrong choice cannot execute.

**Tools beyond the browser.** Web search, file writing inside `workspace/`, PDF/docx/xlsx reading, downloads, and terminal commands.

**🔐 Approval lock.** Anything with side effects (running a command, installing, deleting) pauses with the exact command on screen and **Approve / Deny** buttons. No answer in 2 minutes means *deny*. Destructive commands and secret reading stay blocked whatever you set.

**Permissions centre.** Six scopes — browser, terminal, files, network, clipboard, downloads — each with `allow` / `ask` / `deny`. Every change and every approval is written to `artifacts/audit.jsonl`.

**⚙️ Models & parameters, per model.** The sidebar lists the live models from every provider you hold a key for and renders only the controls each selected model really accepts — a rejected parameter is remembered instead of sent, so switching models cannot leave stale settings behind. Presets (*Fast*, *Balanced*, *Deep*, *Browser*, *Coding*), saved profiles, no `.env` editing.

**🧪 Isolated browser (optional).** Point the agent at a **Neko** container in Docker instead of your tab, watch it live by WebRTC, and keep your own cookies and accounts untouched.

**Laya: a local decision router (optional).** A 322M non-autoregressive engine routes and classifies missions in any language, on your CPU, in milliseconds. Cloud models are only ever used for the reasoning itself. Local LLM runtimes (Ollama, LM Studio, llama.cpp, Jan) were deliberately removed: the agent drives a live web page, which needs the internet anyway. Numbers and limits: [docs/laya.md](docs/laya.md).

## How it works

```text
page → indexed element table → one request → operation + target → execute
```

Each decision is a single network round trip: the model returns the operation (`CLICK`, `TYPE_TEXT`, `SELECT`, `SCROLL_UP`, `SCROLL_DOWN`, `WAIT`, `DONE`, `BLOCKED`) and, for that operation only, which element to act on. Text generation happens only when the operation is `TYPE_TEXT`. Native dropdown options carry an observed option index, and a stale decision invalidates instead of executing blindly.

- Loop and snapshotting: [`jev_ultrafast/agent.py`](jev_ultrafast/agent.py) · [docs/design.md](docs/design.md)
- Firefox sidebar, bridge and native messaging: [docs/firefox-extension.md](docs/firefox-extension.md)
- Full product and architecture specification: [docs/firefox-agent-specification.md](docs/firefox-agent-specification.md)

## Performance

The reference loop completed a real Google Flights task — Zürich → London, one way, one adult, typed city names generated by the model — in **7.07 s** at 1× speed, with a median decision latency of 178 ms. It is a small controlled comparison against the pre-optimisation loop, not a general benchmark; the same example still ships in [`examples/flights.py`](examples/flights.py).

Measurements, method and raw evidence: [docs/performance.md](docs/performance.md) · [docs/flights-measurement.json](docs/flights-measurement.json).

## Requirements

| | |
| --- | --- |
| **Firefox** | 109 or newer (the add-on is loaded temporarily; the sidebar is the UI) |
| **Python** | 3.11+ (3.11 / 3.12 / 3.13 tested) |
| **Machine** | anything — the host process uses ~40 MB of RAM and no GPU; 8 GB is plenty |
| **Keys** | one free Groq key. An optional free NVIDIA NIM key upgrades the planner to `z-ai/glm-5.3` |
| **Docker** | optional, only for the isolated browser (≈2 GB of disk) |

## Providers

Any OpenAI-compatible or Anthropic-compatible endpoint can drive any role: Groq, NVIDIA NIM, DeepSeek, OpenRouter, Together, Mistral, xAI, Gemini, your own gateway, or a loopback server (`POLICY_BASE_URL`). The measured-best default arrangement is NVIDIA NIM planning and Groq executing; one key runs all three roles on its own. TypeSafe's Jev policy is still supported through `TYPESAFE_API_KEY` if you have one.

Configuration, presets and self-hosted gateways: [docs/providers.md](docs/providers.md) · which parameters each model really accepts: [docs/model-parameters.md](docs/model-parameters.md).

## Privacy and safety

- **Everything local except the model calls.** The bridge listens on `127.0.0.1` only, checks the `moz-extension://` origin, and the optional web console binds to `127.0.0.1` with a token.
- **Your keys stay on your machine**, written to `.env` by the sidebar, never printed back and never sent anywhere except the provider you chose.
- **The agent cannot leave its workspace.** Files it creates go to `workspace/`; paths outside are refused.
- **Firefox launches the agent itself** over native messaging (a per-user manifest, no admin rights). Closing Firefox stops it; nothing keeps running in the background.
- No telemetry, no accounts, no server of ours in the middle.

## Documentation

| Guide | For |
| --- | --- |
| [EMPEZAR-AQUI.md](EMPEZAR-AQUI.md) (ES) · [docs/getting-started-gui.md](docs/getting-started-gui.md) | Setup with no console |
| [docs/setup-por-sistema.md](docs/setup-por-sistema.md) (ES) | Every OS in detail: commands, verification, uninstall |
| [docs/requisitos.md](docs/requisitos.md) · [docs/requisitos-hardware.md](docs/requisitos-hardware.md) (ES) | Requirements and hardware |
| [docs/firefox-extension.md](docs/firefox-extension.md) · [docs/firefox-agent-specification.md](docs/firefox-agent-specification.md) | How the sidebar, bridge and hosts work |
| [docs/providers.md](docs/providers.md) · [docs/model-parameters.md](docs/model-parameters.md) | Models, keys, per-model parameters |
| [docs/laya.md](docs/laya.md) (ES) | The local decision router |
| [docs/evaluacion-a-produccion.md](docs/evaluacion-a-produccion.md) (ES) · [docs/calidad-a-escala.md](docs/calidad-a-escala.md) (ES) | Honest evaluation and the mission battery |
| [docs/](docs/README.md) | Complete index |

## Development

```bash
git clone https://github.com/LockerDocx/firefox-ai-agent.git
cd firefox-ai-agent
python -m venv .venv && .venv/bin/pip install -e ".[documents]" pytest ruff   # Windows: .venv\Scripts\pip
.venv/bin/python -m pytest -q        # 413 tests, no paid API calls
.venv/bin/python -m ruff check .
```

CI runs the full suite on **Python 3.11, 3.12 and 3.13**, inside real **openSUSE Leap 15.6** and **Tumbleweed** containers (zypper, the starter, native-messaging registration) and on **Windows** (stdlib native messaging, registry, key handling) — plus the whole suite again under a non-UTF-8 locale, which is how the Windows encoding bugs were caught. Model checks that need keys live in separate workflows and never run on forks.

Entry points: `jev-firefox` (sidebar host), `jev-firefox-native` (native-messaging host), `jev-register-host` (`--status` / `--unregister`), `jev` (local web console at `127.0.0.1:8766`).

## Credits and license

Built on **[Browser Use](https://github.com/browser-use/browser-use)**'s `jev-ultrafast` reference loop and **[Browser Harness](https://github.com/browser-use/browser-harness)**; the Firefox sidebar, native-messaging host, cross-platform starters, tools, permissions and model panel are this project's work. [Laya](https://github.com/NandhaKishorM/laya) (Convai Innovations) is Apache-2.0.

MIT — the original copyright notice is preserved in [LICENSE](LICENSE).
