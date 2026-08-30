# Lazi-Bot — LinkedIn Auto-Pilot

> The slightly overweight, dirty-looking desktop companion that applies to jobs for you.

**Lazi-Bot** is a PySide6 desktop app that unifies 5 LinkedIn job engines under one roof:
`EasyApplyJobsBot`, `linkedin-aihawk`, `auto-job-applier`, `linkedin-bot`, `Job-apply-AI-agent`, and the new **page-agent** (Phase 2, Engine 6).

---

## Quick Start

```powershell
run.bat
```

First run creates a `venv`, installs dependencies, and launches the GUI.

## Features

| Feature | Description |
|---|---|
| **Persona system** | One browser profile + config per job-search persona |
| **5+1 engines** | Each engine has an adapter under `app/engines/` |
| **Shared scraper** | Discover jobs once → dispatch to selected engine |
| **Provider abstraction** | Poolside, OpenAI, Google, or form-only (no key needed) |
| **LaziBrain (Phase 2)** | Enhanced ReAct loop with event bus + 6-engine tool registry |
| **MCP Bridge (Phase 2)** | page-agent connects as Engine 6 via JSON-RPC over stdio |
| **Vault** | Encrypted local memory for corrections + learnings |
| **Self-Healer** | Auto-diagnoses + broadcasts fixes across all running bots |

---

## Architecture

```
linkedin-autopilot/
├── app/
│   ├── main.py              ← PySide6 GUI + AppController
│   ├── lazibot.py            ← LaziBrain (Phase 2: delegates to lazibrain_core)
│   ├── lazibrain_core.py     ← Enhanced ReAct loop + Qt event bus
│   ├── mcp_bridge.py         ← MCP server (stdio) + MCPBridge client
│   ├── tool_decorator.py     ← @register_tool + ToolRegistry
│   ├── scraper.py            ← Shared LinkedIn job discovery
│   ├── bot_runner.py         ← Engine dispatcher + plugin loader
│   └── engines/              ← Thin adapters for each engine
├── engines/                   ← MIT-licensed copies of 5 bots (read-only)
├── personas/                  ← Per-persona config + browser profile
├── vault/                     ← Encrypted vault (gitignored)
├── PLAN.md                    ← Full architecture + Phase 2 plan
└── AGENTS.md                  ← Agent/dev documentation
```

## Phase 2 Status

| Component | Status |
|---|---|
| `@register_tool` + `ToolRegistry` | ✅ Done |
| MCP Bridge (`MCPServer` + `MCPBridge`) | ✅ Done |
| Enhanced ReAct loop (`LaziBrainCore`) | ✅ Done |
| 6-engine tool registry | ✅ Done |
| page-agent integration (Engine 6) | 🔜 Next |
| Resume tailoring pipeline | 🔜 Phase 3 |

## Setup

```powershell
# Requirements
python >= 3.11
Google Chrome (for Selenium-based engines)
```

```powershell
run.bat
```

Or manually:

```powershell
python -m venv venv
.\venv\Scripts\activate
pip install PySide6 openai keyring
python app/main.py
```

## Key Decisions (see `PLAN.md` for full rationale)

- **page-agent** (Alibaba, 28.9k stars) = Engine 6 anti-bot fallback — JS injected as
  first-party, communicates with LaziBrain via MCP over stdio
- **No Redis** — in-process ring buffer + DB-backed `pending_approvals` for agent harness
- **No worktrees** — one working copy per branch, branch-only isolation
- **Squash merge** — PRs squash when > 3 commits, conventional commits `feat(svc):`
- **NO worktrees** in this repo — confirmed with user

## GitHub Actions

| Workflow | Trigger | What it does |
|---|---|---|
| `ci.yml` | push/PR to main | ruff lint + compile check + pytest |
| `dependabot.yml` | weekly | pins pip + npm vulnerabilities in engine submodules |

---

*Built with PySide6 · Powered by LaziBrain · Licensed under MIT (engines)*
