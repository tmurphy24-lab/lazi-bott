# Domain Docs

How the engineering skills should consume this repo's domain documentation when exploring the codebase.

## Before exploring, read these

- **`CONTEXT.md`** at the repo root, or
- **`CONTEXT-MAP.md`** at the repo root if it exists: it points at one `CONTEXT.md` per context. Read each one relevant to the topic.
- **`docs/adr/`**: read ADRs that touch the area you're about to work in. In multi-context repos, also check `src/<context>/docs/adr/` for context-scoped decisions.

If any of these files don't exist, **proceed silently**. Don't flag their absence; don't suggest creating them upfront. The `/domain-modeling` skill (reached via `/grill-with-docs` and `/improve-codebase-architecture`) creates them lazily when terms or decisions actually get resolved.

## File structure

Single-context repo:

```
/
├── CONTEXT.md
├── docs/adr/
│   └── 0001-<slug>.md
├── app/          <- adapters, dispatcher, ReAct core, vault, MCP bridge
└── engines/      <- read-only vendored copies of upstream bots
```

This repo is single-context. `engines/` is vendored third-party code, not a context of its own: it does not get a `CONTEXT.md`.

## Use the glossary's vocabulary

When your output names a domain concept (in an issue title, a refactor proposal, a hypothesis, a test name), use the term as defined in `CONTEXT.md`. Don't drift to synonyms the glossary explicitly avoids.

Until a `CONTEXT.md` exists, take the vocabulary from `AGENTS.md`, which already names the load-bearing terms: engine, adapter, dispatcher, tool registry, vault, self-healer, MCP bridge, run mode.

If the concept you need isn't in the glossary yet, that's a signal: either you're inventing language the project doesn't use (reconsider) or there's a real gap (note it for `/domain-modeling`).

## Flag ADR conflicts

If your output contradicts an existing ADR, surface it explicitly rather than silently overriding:

> _Contradicts ADR-0007 (event-sourced orders), but worth reopening because…_

Architectural decisions in this repo currently live in `PLAN.md` (see its Decision 5 on Google SSO). Treat a numbered Decision in `PLAN.md` as an ADR until it is migrated into `docs/adr/`.
