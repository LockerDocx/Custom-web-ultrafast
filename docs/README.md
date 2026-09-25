# Documentation index

Everything the project documents, sorted by what you are trying to do. Spanish guides are marked **(ES)**; the rest are in English.

## Start here

| Document | What it covers |
| --- | --- |
| [../EMPEZAR-AQUI.md](../EMPEZAR-AQUI.md) **(ES)** | The five-step setup with pictures of what you will see, no console at all |
| [getting-started-gui.md](getting-started-gui.md) | The same walkthrough in English, including how to publish your own copy from the GitHub web UI |
| [setup-por-sistema.md](setup-por-sistema.md) **(ES)** | Setup **and daily use**, system by system (openSUSE/SUSE, Ubuntu/Debian/Mint, Fedora/RHEL/Rocky, Arch, Windows, macOS, snap/Flatpak Firefox): exact commands, how to verify, how to update and uninstall |

## Project

| Document | What it covers |
| --- | --- |
| [../CHANGELOG.md](../CHANGELOG.md) | Every version: what shipped, what was fixed, and what has not been measured yet |
| [../AGENTS.md](../AGENTS.md) | The contracts a contributor must keep working |

## Requirements and hardware

| Document | What it covers |
| --- | --- |
| [requisitos.md](requisitos.md) **(ES)** | What the agent needs: Firefox, Python, ports, keys, and what each requirement is for |
| [requisitos-hardware.md](requisitos-hardware.md) **(ES)** | Real memory and disk numbers (host ≈ 40 MB; the optional isolated browser ≈ 2 GB) |

## How it works

| Document | What it covers |
| --- | --- |
| [design.md](design.md) | The core idea: one request returns the operation and its target, from an indexed element table |
| [firefox-extension.md](firefox-extension.md) | The sidebar, the local bridge, native messaging, and the message protocol |
| [firefox-agent-specification.md](firefox-agent-specification.md) | The full product and architecture specification, MVP by MVP |
| [model-parameters.md](model-parameters.md) | How each model's real parameter surface is discovered instead of hardcoded |

## Configuration

| Document | What it covers |
| --- | --- |
| [providers.md](providers.md) | Every provider preset, keys, base URLs, dialects, self-hosted gateways, role overrides |
| [laya.md](laya.md) **(ES)** | The optional local decision router: what it does, measured numbers, honest limits |

## Measurements and evaluation

| Document | What it covers |
| --- | --- |
| [performance.md](performance.md) ⚠️ | **Upstream numbers** (Chrome + TypeSafe Jev + Mercury, not this build): 7.07 s at 1×, matched comparison, raw evidence |
| [performance-prepared.md](performance-prepared.md) ⚠️ | Upstream historical recording, kept for reference |
| [calidad-a-escala.md](calidad-a-escala.md) **(ES)** | The 241-mission battery: accuracy, dangerous routings, latency |
| [evaluacion-a-produccion.md](evaluacion-a-produccion.md) **(ES)** | An honest evaluation: what is production-ready and what is not |
| `*-measurement.json`, `flights-result.png`, `inspector.png`, `demo.gif/mp4` ⚠️ | The raw evidence and footage behind those upstream pages — recorded with Chrome and TypeSafe's model, not with this build |

## Archive

Work that is finished or superseded, kept because it explains how the project got here.

| Document | Why it is archived |
| --- | --- |
| [archive/historia-ramas.md](archive/historia-ramas.md) **(ES)** | Where each parallel line of work ended up; the merge is done and `main` is the project |
| [archive/launch-draft.md](archive/launch-draft.md) | An early announcement draft |
| [archive/banner-browser-use.svg](archive/banner-browser-use.svg) | The original banner from the upstream project this one started from |
