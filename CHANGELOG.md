# Changelog

Notable changes per version. Versions 0.5.0 to 0.8.0 shipped inside the code line and are listed here even
though they never had a GitHub release; everything else has a tag.

**On the name:** until v0.11.0 the project and the add-on were called *Jev Ultrafast* — borrowed from
**TypeSafe AI**'s Jev model, because the upstream project this fork started from demonstrates it. It is not
ours, and it is gone from anything a user sees: the name is now *AI Agent for Firefox*. Internal
identifiers (`jev_ultrafast`, the `jev-*` console scripts, the `JEV_*` variables, the extension id and the
native-messaging host name) were kept on purpose, so installations and Firefox registrations that already
exist keep working.

**On the measurements:** the performance figures in `docs/` were recorded by the upstream project, on
Chrome, with TypeSafe's hosted policy and the Mercury text model. They are labelled as such wherever they
appear. This build drives Firefox with Groq/NVIDIA and has not been measured yet.


## [0.11.0] — 2026-09-25

The version that took the project from "assumed macOS" to the systems people actually run, and that proves
it instead of claiming it.

### Added

- CI that runs the real thing: openSUSE **Leap 15.6** and **Tumbleweed** containers (zypper, the starter,
  install, full suite), a **Windows** job (native messaging over stdio, registry, key handling, starter)
  and Python **3.11 / 3.12 / 3.13** — plus the whole suite again under a non-UTF-8 locale.
- Platform tests that drive the actual starters against fake per-distro interpreters, and per-distro Python
  install hints inside the starter itself.
- Windows interpreter discovery through the `py` launcher, with a warning when `python` is the Microsoft
  Store stub.

### Changed

- `requires-python` lowered to **3.11** (what current distributions still ship as an option), and the
  starter looks for `python3.13` → `python3.12` → `python3.11` → `python3` instead of assuming the first
  `python3` it finds is new enough.
- The user-facing name is **AI Agent for Firefox**; release assets are named `ai-agent-for-firefox-*`;
  the repository is `firefox-ai-agent`.
- README rewritten to describe this project rather than the upstream one it started from.

### Fixed

- Every text file the agent reads or writes declares UTF-8. Without it, a Windows machine under a legacy
  code page could not even start the agent (`snapshot.js` contains non-ASCII characters).
- `.env` is read as `utf-8-sig`, so a key saved by Notepad with a BOM is no longer invisible to the agent.
- SUSE package names in the docs and in CI (`python312`, never `python3.12`).
- A connection-level failure now retries on the plain request path exactly as the streaming path already
  did — a model being woken up no longer kills a run on the first attempt.
- `[project.urls]` no longer swallows the `dependencies` line, which broke every fresh install.


## [0.10.0] — 2026-09-25 — Firefox starts the agent itself

The double-click became optional: Firefox launches the local host through native messaging, so opening the sidebar *is* starting the agent.

### Added

- Native messaging: a per-user manifest registered once (`jev-register-host`, with `--status` and `--unregister`), on Linux, macOS and Windows (registry, no admin rights).
- The host accepts only this add-on (`allowed_extensions`), and it stops when Firefox closes — nothing keeps running in the background.

### Changed

- The double-click starter stays as the documented fallback, and as the route on snap/Flatpak Firefox.

### Fixed

- Registration that a browser can actually launch, after CI proved the first version could not.

## [0.9.0] — 2026-09-25 — The setup happens in Firefox

Setup stopped being a terminal task: the sidebar asks for one key, checks it and configures everything, which is what makes a no-console install real.

Between v0.4.0 and this release, versions 0.5.0 to 0.8.0 shipped inside the code line without a GitHub release: the parameter surface became the model's, the isolated Neko browser, permission centre and audit log landed, local LLM runtimes were dropped on purpose, and one free key started configuring all three roles.

### Added

- Graphical setup in the sidebar: paste one free API key, it is validated against the provider, written to `.env` and applied immediately — no restart, no file editing.
- The panel reports what the key bought (`planner … · policy … · text …`) and reopens the card with the provider's exact error when a key is rejected.
- CI guard that fails if the double-click starters lose their executable bit.

### Fixed

- The executable bit itself, which the guard immediately caught.

## [0.4.0] — 2026-09-23 — Quality at scale: 241-mission battery, provider bench and a live E2E

The version that answered the question the previous ones left open: does any of this still hold at scale? It answered with real resources in CI, not with simulations.

### Added

- Routing battery: 241 labelled missions — 6 languages × 36 core missions plus 25 adversarial ones (mixed intent, multi-clause, bilingual, telegraphic, typos) — scoring raw Laya against the shipped stack and tracking *dangerous* confusion above all.
- Provider bench that probes live endpoints instead of trusting documentation.
- Live flights mission in CI: real providers, real browser, a token budget per provider and a report that survives even a failed run.

### Fixed

- Tool signals outrank a confident page answer; suggestions complete before the model is asked to choose; the demo's expired date no longer makes the mission impossible.

## [0.2.0] — 2026-09-23 — The whole fork merged: MVP-1 to MVP-6, Laya and the security pass

The first version containing all of the fork's work in one place (PR #1: 27 commits, about 9,100 lines).

### Added

- Model catalogue and provider layer (MVP-1/2): presets, key handling, per-role selection.
- Tools, skills and the orchestrator (MVP-3/4): web search, files, document parsing, terminal commands.
- Command approvals (MVP-4): side-effecting commands pause for an explicit yes, and a timeout means no.
- Streaming responses, saved profiles and run history (MVP-6).
- Laya integration with a measured confidence gate, published next to the vendor claims.

## [0.1.0] — 2026-09-22 — Pluggable providers, planner–executor loop, Firefox sidebar

First release of this fork: the reference browser loop, rebuilt around providers you choose and a Firefox sidebar that drives the tab you are looking at.

### Added

- Pluggable model providers (NVIDIA NIM, Groq, OpenRouter, OpenAI, Anthropic, DeepSeek, Together, Mistral, xAI, Gemini, or your own gateway) with a planner–executor split.
- Firefox WebExtension sidebar and the local bridge it talks to over loopback.
- Double-click starters for Windows, macOS and Linux, plus a Spanish guide written for people who do not use a console (EMPEZAR-AQUI.md).
- CI with automatic release artifacts (source archive, `.xpi`, wheel).
- Laya, the open System One decision engine (Convai Innovations, Apache 2.0), as the optional local router.
- Production security pass: secret redaction, an action audit log, and CPU/memory/file limits on approved commands.


---

*The pattern is simple: a version ships when its own claims can be checked — by tests in the repository, or
by CI on the systems it says it supports.*
