## Merge strategy

**Squash merge** — collapse all commits into one before merging.

Use conventional commits:
```
feat(lazibot): add MCP Bridge for page-agent
fix(scraper): handle empty job list gracefully
refactor(bot_runner): extract engine adapter interface
chore(deps): update ruff to 0.4.0
docs(readme): add Phase 2 status table
```

## PR checklist

- [ ] `ruff check app/` passes (or explicitly noted/ignored)
- [ ] `pytest app/test_phase2.py` passes (headless skip is OK)
- [ ] No secrets or keys in diff
- [ ] New code has docstrings
- [ ] Squash-merge enabled in GitHub PR settings (Settings → General → Allow squash merging ✓)

## What changed?

_Describe the change here._
