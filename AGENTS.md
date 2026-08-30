# linkedin-autopilot

**Unified desktop launcher** for the five existing LinkedIn job bots:
`EasyApplyJobsBot`, `linkedin-aihawk`, `auto-job-applier`, `linkedin-bot`, and
`Job-apply-AI-agent`.

## What it does

- Presents a PySide6 GUI: pick a **Persona** → pick a **Provider** → pick a **Mode/Engine**.
- One **browser profile per persona** — you log into LinkedIn once, it persists.
- One **shared scraper** (`app/scraper.py`) — discovers jobs once, dispatches to the
  selected engine.
- **Provider abstraction**: Poolside, OpenAI, Google, or None — injected as env vars.
- **Run summaries** saved to `runs/` as JSON; **live log panel** during execution.
- **Plugin hooks**: drop `.py` files in `plugins/` that define `before_scrape`,
  `on_job`, or `on_error` functions.

## Layout

```
linkedin-autopilot/
├── app/
│   ├── main.py                  ← PySide6 GUI scaffold
│   ├── scraper.py               ← shared LinkedIn job scraper
│   ├── profile_store.py         ← keyring + Chrome profile management
│   ├── bot_runner.py            ← dispatcher + plugin loader
│   └── engines/                 ← 5 thin adapter wrappers
├── engines/                     ← COPY of the 5 original bots (unmodified except linkedin-bot patches)
├── personas/                    ← per-persona search_config.yaml + browser_profile/
├── runs/                        ← run summaries (JSON)
├── logs/
├── keys/                        ← API key files (gitignored)
└── plugins/                     ← optional hook plugins
```

## Two patched files (in engines/linkedin-bot/)

1. **`utils/ai.py`** — reads `OPENAI_API_BASE_URL` from env so Poolside/Google work.
2. **`easy_apply.py`** — accepts `--jobs` and `--salary` CLI args to bypass the tkinter
   input popup (the only change that lets the dispatcher control the search query).

## Setup

```powershell
cd linkedin-autopilot
run.bat
```

On first run it creates a `venv`, installs deps, and launches the GUI.

## Non-goals

- Does **not** modify the original bots in `C:\Users\trevo\Desktop\.agents\`.
- Does **not** fix `pygame` build failures (cosmetic sound effects in linkedin-bot).
- Does **not** rename `Job-apply-AI-agent` (venv hardcodes the absolute path).

## Known limitations

- **Google SSO intent is unresolved** — see plan Decision 5. Currently "google" provider
  passes through Chrome session only; true OAuth client not implemented.
- **Screen recording** — plan Option C (DOM event logging) chosen over video.
  The `bot_runner.py` does not yet implement the DOM logger; it logs engine stdout only.
- **Credential encryption** — `keyring` for API keys; Chrome profile dir is unencrypted
  on disk (standard Chrome behavior).
