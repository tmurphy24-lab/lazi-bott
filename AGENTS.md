# Lazi-Bot — Agent Dev Guide

> This file is for AI agents. Humans: see `README.md`.

Python 3.11+ desktop app: PySide6 GUI over an openai-compatible LLM client, dispatching six job-application engines.

Repo root: `C:\Users\trevo\Desktop\.agents\linkedin-autopilot`. Engines live in `engines/<name>/` as MIT-licensed read-only copies; their adapters live in `app/engines/`.

`CLAUDE.md` is a one-line pointer at this file, so Claude Code reads everything below through the import.

## Project map

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

<important if="you are about to use git, delete a file, or touch anything under engines/">
1. **NO worktrees.** Work on the main checkout only.
2. **Squash merge** when there are more than 3 commits. Conventional commits: `feat(svc):`, `fix(svc):`, `refactor(svc):`.
3. **The original bots in `C:\Users\trevo\Desktop\.agents/` are untouched.** All copies live in `engines/`.
4. **Delete via `recycle.ps1`.** No `Remove-Item`, the Recycle Bin guard is intentional.
</important>

<important if="you are adding or modifying an engine, tool, or adapter">

Six engines are registered:

| # | Name | Adapter | Notes |
|---|---|---|---|
| 1 | `easyapplyjobsbot` | `app/engines/easyapplyjobsbot_adapter.py` | Volume, no cover letter |
| 2 | `linkedin_aihawk` | `app/engines/linkedin_aihawk_adapter.py` | AI-powered, needs Chrome |
| 3 | `auto_job_applier` | `app/engines/auto_job_applier_adapter.py` | Custom prompts |
| 4 | `linkedin_bot` | `app/engines/linkedin_bot_adapter.py` | Patch: env `OPENAI_API_BASE_URL` |
| 5 | `job_apply_ai_agent` | `app/engines/job_apply_ai_agent_adapter.py` | Batch processing |
| 6 | `page_agent` | `app/mcp_bridge.py` — `MCPBridge` | Alibaba JS bookmarklet, MCP stdio |

Tools register at import time through `@register_tool` from `app/tool_decorator.py`. A tool takes the query/location/max_jobs shape, calls `signal.raise_if_aborted()` at checkpoints, and returns `{"content": [{"type": "text", "text": ...}]}`. See any existing adapter in `app/engines/` for the pattern.
</important>

<important if="you are debugging startup, singletons, or the control flow between the loop and the bridge">

```
LaziBrain (QObject)
├── LaziBrainCore (enhanced ReAct loop)
│   ├── observe → think → reflect → act → loop (max 10 iterations)
│   ├── event bus: status_changed / history_changed / activity_changed (Qt signals)
│   └── _AbortController for cancellation
├── MCPBridge (stub mode default)
│   ├── MCPServer: hosts tools for page-agent to call
│   └── page-agent: JS-injected browser agent, over MCP stdio
└── ToolRegistry (@register_tool decorator, 6 engines + built-in helpers)
```

Boot order:
```
AppController.__init__
  └─ setup_lazi_integration(controller)
       ├─ _boot_mcp_bridge()     → MCPBridge (synchronous, fast)
       └─ _background_boot()     → Vault + SelfHealer + HiveMindFixBroadcaster (async)
```
After boot, `lazi_integration.get_vault()` and `lazi_integration.get_mcp_bridge()` reach the singletons from anywhere.
</important>

<important if="you are configuring an LLM provider or authentication">

| Provider | Env var |
|---|---|
| Poolside | `POOLSIDE_API_KEY` |
| OpenAI | `OPENAI_API_KEY` |
| Google | `GOOGLE_API_KEY` |
| None | form-only mode, no key needed |

Google OAuth client is **not yet implemented**, see `PLAN.md` Decision 5. It currently falls through to the Chrome session cookie only.
</important>

<important if="you are handling a Dependabot alert or a vulnerability in a vendored engine">
Tracked by `.github/dependabot.yml` on a weekly schedule. Fix by running `npm audit fix` or `pip-audit` in the relevant `engines/<name>/` directory and committing the lockfile updates.
</important>

<important if="you are filing an issue, triaging, or writing domain docs for this repo">
Config for Matt Pocock's engineering skills (`/grill-me`, `/tdd`, `/triage`, `/to-spec`, `/to-tickets`, `/wayfinder`, and the rest). The skills are installed once at user level and shared by every agent; only the files below are per-repo.

- **Issue tracker:** GitHub Issues on `tmurphy24-lab/lazi-bott` via the `gh` CLI. Upstream engine bugs are not this repo's backlog. See `docs/agents/issue-tracker.md`.
- **Triage labels:** the five canonical roles, used verbatim as label strings; all five exist on the repo. See `docs/agents/triage-labels.md`.
- **Domain docs:** single-context, one `CONTEXT.md` plus `docs/adr/` at the repo root. `engines/` is vendored code, not a context. See `docs/agents/domain.md`.
</important>
