# Lazi-Bot — Agent Dev Guide

> This file is for AI agents. Humans: see `README.md`.

## Stack

- **Runtime**: Python 3.11+, PySide6 GUI, openai-compatible LLM client
- **Repo root**: `C:\Users\trevo\Desktop\.agents\linkedin-autopilot`
- **Engines live here**: `engines/<name>/` (MIT-licensed copies, read-only)
- **Engine adapters live here**: `app/engines/` (wraps each engine for the dispatcher)

## Engine Registry (Phase 2 — 6 engines)

| # | Name | Adapter | Notes |
|---|---|---|---|
| 1 | `easyapplyjobsbot` | `app/engines/easyapplyjobsbot_adapter.py` | Volume, no cover letter |
| 2 | `linkedin_aihawk` | `app/engines/linkedin_aihawk_adapter.py` | AI-powered, needs Chrome |
| 3 | `auto_job_applier` | `app/engines/auto_job_applier_adapter.py` | Custom prompts |
| 4 | `linkedin_bot` | `app/engines/linkedin_bot_adapter.py` | Patch: env `OPENAI_API_BASE_URL` |
| 5 | `job_apply_ai_agent` | `app/engines/job_apply_ai_agent_adapter.py` | Batch processing |
| 6 | `page_agent` | `app/mcp_bridge.py` — `MCPBridge` | Alibaba JS bookmarklet, MCP stdio |

## Phase 2 Architecture

```
LaziBrain (QObject)
├── LaziBrainCore (enhanced ReAct loop)
│   ├── observe → think → reflect → act → loop (max 10 iterations)
│   ├── event bus: status_changed / history_changed / activity_changed (Qt signals)
│   └── _AbortController for cancellation
├── MCPBridge (stub mode default)
│   ├── MCPServer: hosts tools for page-agent to call
│   └── page-agent: JS-injected browser agent, communicates via MCP over stdio
└── ToolRegistry (@register_tool decorator, 6 engines + built-in helpers)
```

## Key Files

| File | Purpose |
|---|---|
| `app/lazibrain_core.py` | Enhanced ReAct loop + Qt event bus |
| `app/mcp_bridge.py` | MCP server (stdio) + MCPBridge client |
| `app/tool_decorator.py` | `@register_tool`, `Tool`, `get_tool_registry()` |
| `app/lazibot.py` | `LaziBrain` (delegates to core), `LaziDock`, `TheCouch` |
| `app/lazi_integration.py` | Boot sequence: vault + self-healer + MCP bridge |
| `app/scraper.py` | Shared job discovery (LinkedIn, Indeed, RemoteOK, Glassdoor) |
| `app/bot_runner.py` | Engine dispatcher + plugin hooks |
| `app/vault.py` | Encrypted local memory |
| `app/self_healer.py` | LLM-powered self-diagnosis + fix broadcasting |

## Tool Registration

Tools are registered at import time via `@register_tool`:

```python
from app.tool_decorator import register_tool

@register_tool(
    name="my_engine",
    description="What it does",
    input_schema={"type": "object", "properties": {...}},
)
def my_engine(query: str, location: str, max_jobs: int = 50, signal=None):
    signal.raise_if_aborted()  # check at checkpoints
    return {"content": [{"type": "text", "text": "result"}]}
```

## Hard Rules

1. **NO worktrees** — work on main checkout only
2. **Squash merge** when > 3 commits — conventional commits: `feat(svc):`, `fix(svc):`, `refactor(svc):`
3. **Original bots in `C:\Users\trevo\Desktop\.agents/` are untouched** — all copies live in `engines/`
4. **Delete via `recycle.ps1`** — no `Remove-Item`; the Recycle Bin guard is intentional

## Boot Sequence

```
AppController.__init__
  └─ setup_lazi_integration(controller)
       ├─ _boot_mcp_bridge()     → MCPBridge (synchronous, fast)
       └─ _background_boot()     → Vault + SelfHealer + HiveMindFixBroadcaster (async)
```

After boot, call `lazi_integration.get_vault()` and `lazi_integration.get_mcp_bridge()`
from anywhere to access singletons.

## Provider Config

| Provider | Env var |
|---|---|
| Poolside | `POOLSIDE_API_KEY` |
| OpenAI | `OPENAI_API_KEY` |
| Google | `GOOGLE_API_KEY` |
| None | form-only mode, no key needed |

## Google SSO

Google OAuth client **not yet implemented** — see `PLAN.md` Decision 5. Currently
falls through to Chrome session cookie only.

## Dependabot

Vulnerabilities in vendored engine submodules are tracked by `.github/dependabot.yml`
(weekly schedule). Fix by running `npm audit fix` or `pip-audit` in the relevant
`engines/<name>/` directory and committing the lockfile updates.
