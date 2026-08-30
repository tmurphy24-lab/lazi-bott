# Lazi-Bot — Master Plan
**Status**: Draft | **Version**: 1.1 | **Updated**: 2026-08-30

---

## 0. Architecture Realignment — What page-agent Changed

> Found via https://github.com/alibaba/page-agent (Apache/MIT, 28.9k stars)

### What page-agent Is

A **JavaScript bookmarklet** that injects directly into any web page as a first-party script. No browser extension, no Python, no Selenium. It runs in the DOM, gives the page its own AI agent, and communicates via MCP.

```
Traditional (ours):   Python/Selenium → remote browser → anti-bot detects it
page-agent way:       JS bookmarklet → injected into page → IS first party → invisible
```

### What We Learned and Are Adopting

| page-agent Pattern | How We Adopt It |
|---|---|
| **MacroTool** — LLM returns `{ evaluation_previous_goal, memory, next_goal, action }` | LaziBrain Enhanced ReAct loop with explicit reflection step |
| **EventTarget** — `statuschange`, `historychange`, `activity` | LaziBrain event bus (our existing `_events` dict → proper event system) |
| **PageController** — async DOM extraction, no screenshots | `DOMExtractor` class — dehydrates page HTML → simplified text for LLM context |
| **SimulatorMask** — visual overlay blocks user during automation | `AppController.show_mask()` / `hide_mask()` |
| **MCP Server** — page-agent controllable from outside | LaziBrain MCP Bridge: Python side (FastMCP) ↔ Browser side (page-agent) |
| **Tool executor with AbortSignal** — cancellable tool calls | `@tool` decorator with signal support |
| **6-step ReAct** — observe → think → reflect → act → loop | LaziBrain loop gains explicit `reflect` and `plan` steps |

### The 6th Engine: page-agent

```
┌──────────────────────────────────────────────────────────────────────┐
│                     LinkedIn.com (or any job site)                   │
│   page-agent.js injected as bookmarklet                              │
│   ↕ communicates via MCP (STDIO or WebSocket)                      │
└─────────────────────────────┬──────────────────────────────────────┘
                              │
                   LaziBrain MCP Bridge (Python)
                              │
                   LaziBrain ↔ tool registry ↔ 5 Python engines
```

**When to use page-agent instead of Python scrapers:**
- LinkedIn blocks Selenium (captcha, anti-bot detection)
- Job descriptions loaded via JS (React/Vue SPA)
- Fast Apply forms that require real browser DOM interaction
- Any dynamic page where Selenium gets blocked

**When to keep using our Python scrapers:**
- High-volume background scraping (no browser overhead)
- API-backed sites (Indeed JSON feeds, RemoteOK)
- Stable, predictable page structures

### MCP Bridge Architecture

```
Browser (page-agent)                    Python (LaziBrain)
──────────────────                    ─────────────────
page-agent instance    ←── MCP ────→    FastMCP server
DOM actions           ←── stdio ────→   LaziBrain tool calls
                      (or WebSocket for dev)
```

MCP is the **wiring layer** between in-browser intelligence (page-agent) and our Python supervisor (LaziBrain). LaziBrain hosts an MCP server; page-agent is the MCP client. This is what makes Lazi-Bot fundamentally different from a simple bot launcher.

---

## Vision

> *"Lazi sits on your couch, watching all your job bots work. When one breaks, Lazi fix-es it. When a new job fires, Lazi routes it. When you need answers, Lazi knows. The vault holds everything. The hive mind learns."*

Lazi-Bot is a **self-healing, hive-mind job application platform** — not just a GUI launcher, but an AI agent orchestrator that:
1. Connects 5 LinkedIn bots + page-agent (Engine 6) as tools it can call
2. Scrapes cross-platform (LinkedIn + Indeed + Glassdoor + RemoteOK)
3. Uses page-agent as anti-bot fallback for blocked sites
4. Learns from failures and self-heals
5. Uses an encrypted vault as the single source of truth
6. Tailors resumes per job using LLM
7. Gives you a fridge-full of analytics

---

## 1. System Architecture

```
┌──────────────────────────────────────────────────────────────────┐
│                      Lazi-Bot GUI (PySide6)                      │
│  LaziDock │ TheCouch │ Job Jukebox │ Couch Frackbar │ Settings │
└───────────────────────────┬────────────────────────────────────┘
                            │ tool-calling / events
                            ▼
┌──────────────────────────────────────────────────────────────────┐
│                    LaziBrain (Supervisor Agent)                  │
│  • Enhanced ReAct: observe → think → reflect → plan → act     │
│  • Decides: Python scraper vs page-agent vs engine             │
│  • Routes failures → self-heal pipeline                        │
│  • MCP Bridge: controls page-agent in any browser tab           │
│  • Tool registry: 5 engines + page-agent + 12 helper tools   │
└──────┬──────────┬──────────┬──────────┬───────────┬────────────┘
       │          │          │          │           │
   EasyApply  AIHawk  AutoJobApplier  LinkedInBot  JobApplyAgent
       │          │          │          │           │
       └──────────┴────┬─────┴──────────┘           │
                        ▼                               │
┌────────────────────────────────┐                     │
│  Cross-Platform Scraper       │                     │
│  LinkedIn│Indeed│Glassdoor│  │                     │
│  RemoteOK│ZipRecruiter        │                     │
└──────────────┬───────────────┘                     │
               │                                     │
┌──────────────▼───────────────┐   ┌────────────────▼──────────────────┐
│  MCP Bridge (FastMCP)        │◄──│  Engine 6: page-agent (JS)       │
│  Python ↔ browser            │   │  • Injected as bookmarklet         │
└──────────────────────────────┘   │  • Runs AS first party → no anti-bot│
                                   │  • LinkedIn / React SPAs / Fast Apps│
                                   │  • Communicates via MCP STDIO       │
                                   └──────────────────────────────────────┘

┌──────────────────────────────────────────────────────────────────┐
│                      Lazi Vault (Source of Truth)                │
│  credentials/   personas/   sessions/   learnings/   jobs/     │
│  (Fernet)     (YAML)       (JSON)      (.learnings/)  (bloom) │
└──────────────────────────────────────────────────────────────────┘
```

---

## 2. LaziBrain — Supervisor Agent (Enhanced ReAct + Tool Registry)

### 2.1 The Enhanced ReAct Loop (from page-agent)

LaziBrain follows a 5-step loop per iteration — matching page-agent's architecture:

```
Step N:
  1. OBSERVE   → gather browser/page state, push observations
  2. THINK     → LLM generates: evaluation + memory + next_goal + action
  3. REFLECT   → build reflection text from evaluation_previous_goal + memory
  4. ACT       → execute the selected tool, emit activity events
  5. LOOP      → max 10 iterations, then summarize partial results
```

Each step emits one of: `thinking | executing | executed | retrying | error`

LaziBrain also emits:
- `statuschange` — agent transitions: idle → running → completed/error/stopped
- `historychange` — history events updated (persistent, agent memory)
- `activity` — transient real-time feedback for UI only (NOT in LLM context)

### 2.2 Tool Schema — All 6 Engines

```python
TOOLS = [
    # 5 Python engines (existing)
    {
        "name": "easyapplyjobsbot",
        "description": "Best for volume: applies to every job LinkedIn throws at you. "
                       "No cover letter support. Returns applied/failed/skipped counts.",
        "parameters": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Job title or search query"},
                "location": {"type": "string"},
                "max_jobs": {"type": "integer", "default": 50},
                "headless": {"type": "boolean", "default": True},
            },
            "required": ["query", "location"]
        }
    },
    {
        "name": "linkedin_aihawk",
        "description": "AI-tailored applications with cover letter generation. "
                       "Higher quality per application. Slower.",
        "parameters": {
            "type": "object",
            "properties": {
                "job_url": {"type": "string"},
                "tailor_resume": {"type": "boolean", "default": True},
                "cover_letter": {"type": "boolean", "default": True},
            },
            "required": ["job_url"]
        }
    },
    {
        "name": "auto_job_applier",
        "description": "Medium volume, good balance of speed and customization. "
                       "Reads user_config.json for per-field answers.",
        "parameters": {
            "type": "object",
            "properties": {
                "query": {"type": "string"},
                "location": {"type": "string"},
                "max_applications": {"type": "integer", "default": 30},
                "resume_v2": {"type": "boolean", "default": False},
            }
        }
    },
    {
        "name": "linkedin_bot",
        "description": "General-purpose LinkedIn bot with easy_apply mode. "
                       "Supports base_url override for custom LLM endpoints.",
        "parameters": {
            "type": "object",
            "properties": {
                "search_query": {"type": "string"},
                "locations": {"type": "array", "items": {"type": "string"}},
                "base_url": {"type": "string"},
            }
        }
    },
    {
        "name": "job_apply_ai_agent",
        "description": "AI-first agent that reads the full job page and decides "
                       "whether to apply. Best rejection filtering.",
        "parameters": {
            "type": "object",
            "properties": {
                "job_url": {"type": "string"},
                "strict_mode": {"type": "boolean", "default": True},
            },
            "required": ["job_url"]
        }
    },
    # Engine 6: page-agent (via MCP Bridge)
    {
        "name": "page_agent",
        "description": "JavaScript in-page agent. Use when Selenium is blocked by anti-bot, "
                       "for React SPAs, or Fast Apply forms requiring real DOM. "
                       "Communicates via MCP to browser. Returns DOM-extracted content.",
        "parameters": {
            "type": "object",
            "properties": {
                "task": {"type": "string", "description": "Natural language instruction for the browser agent"},
                "tab_url": {"type": "string", "description": "URL of the browser tab to target"},
                "wait_for": {"type": "number", "description": "Seconds to wait after action (default 2)"},
            },
            "required": ["task"]
        }
    },
]
```

### 2.3 LaziBrain Implementation (Enhanced)

```python
class LaziBrain:
    MAX_ITERATIONS = 10
    EVENT_STATUS_CHANGE = "statuschange"
    EVENT_HISTORY_CHANGE = "historychange"
    EVENT_ACTIVITY = "activity"

    def __init__(self, llm, vault, mcp_bridge=None):
        self.llm = llm
        self.vault = vault
        self.mcp_bridge = mcp_bridge  # FastMCP connection to page-agent
        self.tools = build_tool_registry(TOOLS)
        self.history = []
        self._events = {}  # → replace with proper EventTarget later

    def ask(self, task: str) -> ExecutionResult:
        """Main ReAct loop — observe, think, reflect, act, loop."""
        self._emit("statuschange", "running")
        self.history = []
        abort_controller = AbortController()

        for step in range(self.MAX_ITERATIONS):
            # 1. OBSERVE
            observations = self._gather_observations(step)
            for obs in observations:
                self.history.append({"type": "observation", "content": obs})

            # 2. THINK — LLM returns MacroToolInput
            messages = self._build_messages(task)
            result = self.llm.invoke(messages, self._macro_tool, abort_controller.signal)

            macro_input = result.tool_result.input
            reflection = {
                "evaluation_previous_goal": macro_input.get("evaluation_previous_goal", ""),
                "memory": macro_input.get("memory", ""),
                "next_goal": macro_input.get("next_goal", ""),
            }

            # 3. REFLECT — log to history
            self.history.append({
                "type": "step", "step": step, "reflection": reflection,
                "action": macro_input["action"], "usage": result.usage
            })
            self._emit("historychange")

            # Check for done
            action = macro_input["action"]
            action_name = list(action.keys())[0]
            if action_name == "done":
                return ExecutionResult(success=True, data=action[action_name], history=self.history)

            # 4. ACT — execute tool with AbortSignal
            self._emit("activity", {"type": "executing", "tool": action_name})
            try:
                tool_result = self._execute_tool(action_name, action[action_name], abort_controller.signal)
            except Exception as e:
                tool_result = f"[ERROR] {e}"
                self.vault.log_failure(action_name, str(e))

            self._emit("activity", {"type": "executed", "tool": action_name, "result": tool_result})
            self.history.append({"type": "result", "tool": action_name, "result": tool_result})

        # Max iterations reached — summarize partial results
        return ExecutionResult(success=False, data=self._summarize_partial(), history=self.history)

    def _execute_tool(self, name: str, input_data: dict, signal: AbortSignal):
        """Execute tool by name. page-agent goes through MCP bridge."""
        if name == "page_agent":
            return self.mcp_bridge.execute(input_data["task"], tab_url=input_data.get("tab_url"))
        return self.tools[name].execute(input_data, {"signal": signal})
```

### 2.4 MCP Bridge — LaziBrain ↔ page-agent

```python
class MCPBridge:
    """FastMCP server that LaziBrain hosts. page-agent is the MCP client."""

    def __init__(self, playwright_browser=None):
        self.server = FastMCP("lazi-brain-mcp")
        self._register_tools()
        self.playwright_browser = playwright_browser  # for launching page-agent tabs

    def _register_tools(self):
        self.server.add_tool("navigate", self._navigate)
        self.server.add_tool("extract_jobs", self._extract_jobs)
        self.server.add_tool("click_apply", self._click_apply)
        self.server.add_tool("fill_form", self._fill_form)
        self.server.add_tool("get_page_html", self._get_page_html)

    def start(self):
        """Start the MCP server. LaziBrain calls this on boot."""
        self.server.run()  # blocks — run on background thread

    # --- Tools page-agent calls through MCP ---
    def _navigate(self, url: str):
        page = self.playwright_browser.new_page()
        page.goto(url)
        return {"success": True, "url": page.url}

    def _extract_jobs(self, selector: str) -> list[dict]:
        """Called by page-agent after it navigates to a job listing page."""
        # page-agent has already extracted DOM; this tool lets it report structured data back
        return []
```

### 2.5 Lazi Command Router

```python
# Natural language → structured command
LAZI_COMMANDS = {
    r"apply to (\d+) jobs?": "run_engine",
    r"set (\w+) to (.+)": "set_param",
    r"blacklist (.+)": "add_blacklist",
    r"swap.*resume": "set_resume",
    r"how.*going": "status_check",
    r"why.*fail": "diagnose_failure",
    r"fix.*(.+)": "self_heal",
    r"scrape (.+)": "cross_platform_scrape",
    r"use.*page.?agent": "page_agent_scrape",      # NEW: route to Engine 6
    r"linkedin.*blocked": "page_agent_scrape",       # NEW: anti-bot fallback
    r"tailor.*resume": "tailor_for_job",
    r"cover letter for (.+)": "generate_cover_letter",
}
```

---

## 3. Cross-Platform Job Scraper

### 3.1 Scraper Decision Tree

```
Job scrape requested
    │
    ├── LinkedIn?
    │       │
    │       ├── Selenium works (no captcha)?
    │       │    → Python scraper (scrapers/linkedin.py)
    │       │
    │       └── Anti-bot blocks Selenium?
    │            → page-agent Engine 6 (MCP Bridge)
    │
    ├── Indeed?
    │    → Python scraper (scrapers/indeed.py) — JSON feed
    │
    ├── Glassdoor?
    │    → Python scraper (scrapers/glassdoor.py)
    │
    ├── RemoteOK?
    │    → Python scraper (scrapers/remoteok.py) — JSON feed
    │
    └── Unknown / React SPA?
       → page-agent Engine 6 (DOM injection)
```

### 3.2 Unified Job Schema

```python
@dataclass
class UnifiedJob:
    source: str                    # "linkedin" | "indeed" | "glassdoor" | "remoteok"
    source_url: str
    job_id: str

    title: str
    company: str
    location: str
    remote: bool
    salary_min: Optional[int]
    salary_max: Optional[int]
    currency: str = "USD"

    description: str
    posted_days_ago: int
    easy_apply: bool
    hiring_fast: bool              # "Fast Response" badge

    employer_urgency: str          # "none" | "medium" | "high"
    ats_type: Optional[str]         # "greenhouse" | "workday" | "lever" | None
    level: str                     # "entry" | "mid" | "senior" | "lead" | "executive"
    department: Optional[str]
    tags: List[str]
    raw_metadata: dict
```

### 3.3 Scraper Adapters

| Platform | Adapter | Status | Key Selectors |
|---|---|---|---|
| LinkedIn | `scrapers/linkedin.py` | existing (`app/scraper.py`) | `[data-occludable-job-id]`, `.base-card` |
| LinkedIn (anti-bot) | `page_agent` (Engine 6) | **NEW** | DOM via page-agent MCP |
| Indeed | `scrapers/indeed.py` | existing | `.jobsearch-JobTitle`, `.company_location` |
| Glassdoor | `scrapers/glassdoor.py` | existing | `.css-16l4uv7`, `.css-1rr4iq7` |
| RemoteOK | `scrapers/remoteok.py` | existing | `.jobs-board__job-link` |
| ZipRecruiter | `scrapers/ziprecruiter.py` | **new** | `.job_search_result` |

### 3.4 Deduplication

- Hash `normalized_title + normalized_company + location` → dedup across all sources
- Store in vault: `vault/jobs/dedup_index.json` (bloom filter for speed)

---

## 4. Lazi Vault — Source of Truth

### 4.1 Vault Structure

```
vault/
├── credentials/           ← Fernet-encrypted (one file per persona)
│   └── {persona}/
│       ├── credentials.vault      # LinkedIn session cookies, password
│       └── api_keys.vault         # Per-provider API keys
├── personas/
│   └── {persona}/
│       ├── search_config.yaml    # Job search parameters
│       ├── profile.yaml          # Personal info + resume path
│       └── blacklist.yaml        # Company + title denylist
├── sessions/
│   └── {persona}/
│       └── run_{timestamp}.json  # Run summaries
├── learnings/
│   ├── errors.jsonl             # Structured error log (append-only)
│   ├── corrections.jsonl         # User corrections
│   └── fixes_applied.jsonl       # Self-heal actions taken
├── jobs/                        # Unified job cache
│   ├── dedup_index.json         # Bloom filter
│   └── {persona}/
│       └── jobs.jsonl           # Discovered jobs (append-only)
└── plugins/
    └── {plugin}/                # Per-persona plugin overrides
```

### 4.2 Fernet Vault API

```python
class Vault:
    KEYRING_SERVICE = "lazi-bot-vault"

    def get_credential(self, persona: str, key: str) -> Optional[str]:
        """Decrypt and return a credential from the vault."""
        encrypted = self._read(f"vault/credentials/{persona}/credentials.vault")
        data = json.loads(self._fernet.decrypt(encrypted))
        return data.get(key)

    def set_credential(self, persona: str, key: str, value: str) -> None:
        """Encrypt and save a credential."""
        path = f"vault/credentials/{persona}/credentials.vault"
        existing = json.loads(self._fernet.decrypt(self._read(path))) if Path(path).exists() else {}
        existing[key] = value
        self._write(path, self._fernet.encrypt(json.dumps(existing).encode()).decode())

    def get_persona_config(self, persona: str) -> dict:
        """Load persona YAML files, merge with defaults."""
        ...

    def log_failure(self, engine: str, error: str, context: dict) -> None:
        """Append a structured error to learnings/errors.jsonl."""
        with open("vault/learnings/errors.jsonl", "a") as f:
            f.write(json.dumps({
                "timestamp": datetime.utcnow().isoformat(),
                "engine": engine,
                "error": error,
                "context": context,
                "resolved": False,
            }) + "\n")
```

---

## 5. Self-Healing System (.learnings/)

### 5.1 Error → Fix Pipeline

```
Engine fails
    │
    ▼
lazi_brain._log_failure()
    │
    ▼
vault/learnings/errors.jsonl ← appended (append-only log)
    │
    ▼
SelfHealer.run()   ← called after every failed run
    │
    ├── Error already seen? → apply known fix from fixes_applied.jsonl
    │
    ├── Error is new?
    │   ├── LaziBrain diagnoses: "why did this fail?"
    │   ├── LaziBrain proposes: "here's how I'd fix it"
    │   ├── If confidence > 0.8 → auto-apply fix
    │   └── If confidence < 0.8 → ask user: "Should I try this fix?"
    │
    └── Fix applied → log to fixes_applied.jsonl
                      update error entry: resolved=True
```

### 5.2 SelfHealer Implementation

```python
class SelfHealer:
    def __init__(self, vault: Vault, llm):
        self.vault = vault
        self.llm = llm
        self.error_history = self._load_errors()

    def run(self, error_entry: dict) -> Optional[dict]:
        """Analyze error and attempt self-heal. Returns fix or None."""
        # Check known fix database first
        known = self._find_known_fix(error_entry["error"])
        if known:
            return self._apply_fix(known)

        # LLM-assisted diagnosis
        diagnosis = self.llm.diagnose(error_entry, self.error_history)

        if diagnosis.confidence > 0.8:
            return self._apply_fix(diagnosis.proposed_fix)
        elif diagnosis.confidence > 0.5:
            return self._propose_fix_to_user(diagnosis)
        else:
            return None

    KNOWN_FIXES = {
        "chromedriver version mismatch": {
            "fix": "webdriver_manager.chrome.ChromeDriverManager().install()",
            "file": "engines/linkedin-bot/easy_apply.py",
        },
        "config.py KAFKA_BOOTSTRAP_SERVERS pydantic error": {
            "fix": "change field type to str, do comma-split in __post_init__",
            "file": "engines/easyapplyjobsbot/config.py",
        },
        "shared_security eager instantiation": {
            "fix": "remove module-level settings = FirewallSettings(), add model_config extra=ignore",
            "file": "packages/shared-security/config.py",
        },
    }
```

### 5.3 Error Categories

| Category | Example | Auto-fix? |
|---|---|---|
| `config` | Wrong field type, missing env var | Yes (high confidence) |
| `auth` | LinkedIn session expired | Prompt user |
| `scraper` | Selector changed, page structure | LLM proposes + user confirms |
| `adapter` | Engine stdout format changed | LLM patches regex |
| `network` | Timeout, 429 rate limit | Yes (retry with backoff) |
| `llm` | API key missing, bad response | Prompt user |

---

## 6. Job Board Page — "The Job Jukebox"

**Name**: *"The Job Jukebox"* — because Lazi drops jobs into your queue like songs.

### 6.1 Branding

- **Tagline**: *"Your job search, on shuffle."*
- **Emoji backdrop**: 🎸🎤🎹 (music theme matching "Jukebox")
- **Color accent**: `#b48a3a` (couch caramel) with electric `#3a5d3a` (stealth green)
- **Icon**: A glowing jukebox emoji `🏪` or `🎰`

### 6.2 Layout

```
┌────────────────────────────────────────────────────┐
│  🎰  THE JOB JUKEBOX          [Filters ▼] [Sort ▼] │
│  "Your job search, on shuffle."                      │
├────────────────────────────────────────────────────┤
│  🔍 Search jobs...                                  │
│  🏢 Company | 📍 Location | 💰 Salary | 📅 Posted    │
├────────────────────────────────────────────────────┤
│  ┌─────────────────────────────────────────────┐   │
│  │ 🎯 Senior Supply Chain Manager              │   │
│  │    Acme Corp  •  Chicago, IL  •  $120-145K │   │
│  │    LinkedIn  •  3 days ago  •  Easy Apply  │   │
│  │    ════════════════════════════════════════  │   │
│  │    [🔥 Apply Now]  [❤️ Save]  [🤖 Tailor]   │   │
│  │    Reactions:  ❤️ x3  🔥 x1  😂 x0        │   │
│  └─────────────────────────────────────────────┘   │
│  ┌─────────────────────────────────────────────┐   │
│  │ 🚚 Logistics Coordinator                   │   │
│  │    ...                                     │   │
│  └─────────────────────────────────────────────┘   │
└────────────────────────────────────────────────────┘
```

### 6.3 Reaction System

Each job card supports emoji reactions (like LinkedIn):

| Reaction | Meaning |
|---|---|
| ❤️ | Saved / interested |
| 🔥 | Hot lead — apply today |
| 😂 | Funny posting / weird vibes |
| 🤔 | Need more research |
| 🚀 | Already applied |

- Stored per persona in `vault/personas/{persona}/reactions.json`
- Reactions show on job card as counts
- Lazi learns from your reactions: if you ❤️ senior roles, prioritize senior titles

### 6.4 Apply Flow

```
Job card "Apply Now" clicked
    │
    ▼
LaziBrain decides: "Which engine should handle this?"
    │
    ├── linkedin_aihawk  →  if cover_letter=True + tailor_resume=True
    ├── easyapplyjobsbot →  if volume mode + no cover needed
    ├── job_apply_ai_agent →  if strict filtering wanted
    │   (anti-bot blocked?)
    │    → page_agent Engine 6 via MCP Bridge
    │
    ▼
Show modal:
  ┌─────────────────────────────────────────┐
  │  Lazi says: "I'm sending this to         │
  │  linkedin-aihawk chief — it'll tailor   │
  │  your resume and fire off a cover letter. │
  │  Sit tight."                            │
  │                                         │
  │  Engine: linkedin-aihawk  [Change ▼]    │
  │  Cover letter: ✅ Generate  [Toggle]   │
  │  Tailor resume: ✅  [Toggle]           │
  │                                         │
  │  [🚀 Send it]    [Wait, tweak first]   │
  └─────────────────────────────────────────┘
    │
    ▼
Engine runs → result → job tracker updated
    │
    ▼
LaziDock: "Applied chief! That's job #47 today. "
         "Your response rate is up 12% this week."
```

---

## 7. Analytics — "The Couch Fridge"

**Name**: *"The Couch Frackbar"* — a fridge full of magnets showing your job search stats.

### 7.1 Fridge Layout

```
┌──────────────────────────────────────────────────────────────┐
│  🧊  THE COUCH FRIDGEBAR  —  "What's in your fridge?"        │
├──────────────────────────────────────────────────────────────┤
│                                                              │
│  ┌────────┐  ┌────────┐  ┌────────┐  ┌────────┐  ┌──────┐│
│  │  📬 47 │  │  💬  8 │  │  🔥  3 │  │  🏆  1 │  │ 📊  ││
│  │ Applied│  │Response │  │Intervw │  │ Offers │  │Rate ││
│  │THIS WK │  │THIS WK │  │THIS WK │  │TOTAL   │  │23%  ││
│  └────────┘  └────────┘  └────────┘  └────────┘  └──────┘│
│                                                              │
│  Fridge shelves (weekly heatmap):                            │
│  Mon 🟩🟩🟩🟩🟩🟩🟩  Tue 🟩🟩🟩🟩🟩🟩🟩  Wed ...           │
│                                                              │
│  Top magnets (by count):                                     │
│  🧲 Supply Chain  🧲 Logistics  🧲 Procurement             │
│  🧲 Manager  🧲 Director  🧲 Operations                     │
│                                                              │
│  Engine leaderboard:                                         │
│  🥇 linkedin-aihawk: 23 apps (best cover letter)           │
│  🥈 easyapplyjobsbot: 15 apps (fastest)                     │
│  🥉 auto-job-applier: 9 apps                               │
│                                                              │
└──────────────────────────────────────────────────────────────┘
```

### 7.2 Interactive Elements

- **Drag magnets** to reorder priority
- **Click a magnet** → filter job board by that tag/keyword
- **Heatmap cells** are clickable → see jobs applied on that day
- **Engine leaderboard** → click to see per-engine stats
- **Trend sparklines** on each magnet block

---

## 8. Testing Strategy

### 8.1 Test Pyramid

```
                    ┌───────────────┐
                    │  E2E Tests   │  ← 5 tests (full flows)
                    │  (test user)  │
                  ┌─┴───────────────┴─┐
                  │  Integration Tests  │  ← 20 tests (engine adapters)
                  │  (test harness)   │
                ┌─┴───────────────────┴─┐
                │     Unit Tests          │  ← 60 tests (individual modules)
                │  (pytest + unittest)   │
                └───────────────────────┘
```

### 8.2 Test Files (Target)

| File | Type | Count | Scope |
|---|---|---|---|
| `_test_new.py` | Unit | 50 | Adapters, vault, scraper |
| `_test_refactor.py` | Unit | 47 | UI components |
| `_test_design_system.py` | Unit | 82 | Design tokens, widgets |
| `_test_user_driven.py` | Integration | 25 | Persona flow |
| `_test_e2e_chain.py` | E2E | 44 | Full run chains |
| `_test_password_browser.py` | Integration | 29 | Vault + browser |
| `_test_10_features.py` | Feature | 60 | All 10 features |
| `_test_self_heal.py` | Unit | 20 | SelfHealer + error log |
| `_test_vault.py` | Unit | 25 | Vault encrypt/decrypt |
| `_test_cross_platform.py` | Unit | 30 | Multi-scraper deduplication |
| `_test_lazibrain.py` | Unit | 20 | LaziBrain tool calls + ReAct |
| `_test_page_agent.py` | **NEW** | 15 | MCP Bridge + page-agent routing |
| `_test_reactions.py` | Unit | 15 | Job card reactions |
| **`TOTAL`** | | **~482** | |

### 8.3 Review Gates

```
PR opened
    │
    ├── ✅ lint / format check
    ├── ✅ type check (mypy)
    ├── ✅ unit tests pass (CI)
    ├── ✅ integration tests pass (CI)
    ├── ✅ E2E smoke test (CI)
    ├── ✅ Lazi self-heal test (CI)
    ├── ✅ Vault encryption test (CI)
    ├── ✅ page-agent MCP bridge test (CI)
    ├── ✅ No new .learnings/UNRESOLVED entries
    ├── ✅ Branding/emoji check (manual, opt-in)
    └── ✅ 2 approvals required
         │
         └── Squash-merge to main
```

### 8.4 Chunking (for large PRs)

> "If your PR changes more than 500 lines in a single file, split it."

1. **Foundation chunk** — structure, types, interfaces (low risk, high value)
2. **UI chunk** — components, pages, widgets
3. **Logic chunk** — LaziBrain, SelfHealer, vault, MCP Bridge
4. **Test chunk** — tests for the new code
5. **Polish chunk** — emoji, branding, animations

Each chunk gets its own PR + review gate.

---

## 9. Migration Plan (v3 → v4)

### Phase 1: Foundation (COMPLETED)
- [x] Create `app/vault.py` — vault structure + Fernet encryption
- [x] Create `app/self_healer.py` — error log + LLM diagnosis
- [x] Create `app/scrapers/` directory with `base.py` + `linkedin.py`
- [x] Add `app/lazibot.py` `_learn()` method — Lazi logs corrections

### Phase 2: Cross-Platform + page-agent (Next)
- [ ] Implement `scrapers/indeed.py` adapter
- [ ] Implement `scrapers/glassdoor.py` adapter
- [ ] Implement job deduplication + `dedup_index.json` bloom filter
- [ ] Update scraper API: `scrape_all(query, location) → List[UnifiedJob]`
- [ ] **NEW**: Add `app/mcp_bridge.py` — FastMCP server in LaziBrain
- [ ] **NEW**: Add `page_agent` as 6th engine in tool registry
- [ ] **NEW**: `@tool` decorator with `AbortSignal` support
- [ ] **NEW**: LaziBrain event bus — `statuschange`, `historychange`, `activity`

### Phase 3: LaziBrain Enhanced ReAct
- [ ] Refactor `LaziDock` to use enhanced ReAct with reflection steps
- [ ] Add `lazi_brain.ask_with_tools()` — ReAct loop with MacroTool pattern
- [ ] `SelfHealer.run()` called automatically after failed engine runs
- [ ] page-agent routing: auto-detect anti-bot → switch to Engine 6

### Phase 4: Job Jukebox + Reactions
- [ ] Create `app/job_board.py` — "The Job Jukebox" page
- [ ] Add emoji reaction system to job cards
- [ ] `vault/personas/{persona}/reactions.json` schema
- [ ] Lazi learns from reactions → preference weighting

### Phase 5: Couch Fridge Analytics
- [ ] Refactor `app/analytics.py` → "The Couch Frackbar"
- [ ] Add draggable magnet blocks
- [ ] Weekly heatmap (7-day grid)
- [ ] Engine leaderboard sparklines

### Phase 6: Branding + Polish
- [ ] Add emoji backdrops to all pages
- [ ] "The Job Jukebox" branding assets
- [ ] "The Couch Frackbar" branding assets
- [ ] Consistent icon set across all tabs

### Phase 7: Testing + Review Gates
- [ ] Add `_test_self_heal.py`, `_test_vault.py`, `_test_cross_platform.py`
- [ ] Add `_test_lazibrain.py`, `_test_page_agent.py`, `_test_reactions.py`
- [ ] Add GitHub Actions CI workflow with review gates
- [ ] Add pre-commit hooks (lint, type-check, test)

---

## 10. Emoji Backdrop Specification

Applied to every page as a subtle CSS backdrop:

```css
/* Applied to page containers */
.page-backdrop {
    background-image:
        radial-gradient(circle at 20% 80%, rgba(180, 138, 58, 0.08) 0%, transparent 50%),
        radial-gradient(circle at 80% 20%, rgba(58, 93, 58, 0.06) 0%, transparent 50%);
    background-attachment: fixed;
}

/* Emoji rain on hover — animated floating emojis in the background */
.emoji-backdrop::before {
    content: "🎯 🚀 💼 🏆 🔥 💬 🧊 🎰 🧲 📊 📈 📋 🎸";
    position: fixed;
    top: 0; left: 0;
    width: 100%; height: 100%;
    font-size: 24px;
    opacity: 0.04;
    pointer-events: none;
    animation: emoji-drift 60s linear infinite;
    z-index: 0;
}
@keyframes emoji-drift {
    0%   { transform: translateY(0) rotate(0deg); }
    50%  { transform: translateY(-20px) rotate(5deg); }
    100% { transform: translateY(0) rotate(0deg); }
}
```

Per-page emoji identifiers:
| Page | Backdrop Emoji |
|---|---|
| PersonaPicker | 👋🌟🚀 |
| TheCouch | 🛋️🏠🛋️ |
| Job Jukebox | 🎰🎸🎹 |
| Analytics (Frackbar) | 🧊🧲📊 |
| AI Assist | 🤖💡✨ |
| Settings | ⚙️🔧🛠️ |
| Scheduler | ⏰🗓️🕐 |
| Job Tracker | 📋📌📎 |

---

## 11. File Structure (Target)

```
linkedin-autopilot/
├── app/
│   ├── main.py                  # PySide6 scaffold
│   ├── lazibot.py               # LaziBrain + LaziDock + TheCouch
│   ├── ui_kit.py                # Design system (SPACING/TYPE/SHADOWS/LaziColors)
│   ├── vault.py                 # Fernet vault + source-of-truth API
│   ├── self_healer.py           # .learnings/ error → fix pipeline
│   ├── mcp_bridge.py            # NEW: FastMCP server — LaziBrain ↔ page-agent
│   ├── job_board.py             # "The Job Jukebox"
│   ├── job_tracker.py            # F1: job application tracking
│   ├── scheduler.py             # F2: cron scheduler
│   ├── analytics.py             # F3: → "Couch Frackbar"
│   ├── ai_assist.py             # F4-F8: cover letter / interview / follow-up / salary / tailor
│   ├── ux.py                    # F9-F10: dark mode + notifications
│   ├── bot_runner.py            # Engine dispatcher
│   ├── scraper.py               # LinkedIn scraper (→ move to scrapers/)
│   ├── scrapers/
│   │   ├── __init__.py
│   │   ├── base.py              # UnifiedJob schema + deduplication + DOMExtractor
│   │   ├── linkedin.py          # Existing scraper logic
│   │   ├── indeed.py            # DONE
│   │   ├── glassdoor.py         # DONE
│   │   └── remoteok.py          # DONE
│   ├── resume_parser.py
│   ├── auto_filler.py
│   ├── profile_store.py
│   └── password_store.py
├── engines/                     # 5 engine copies (read-only)
│   ├── easyapplyjobsbot/
│   ├── linkedin_aihawk/
│   ├── auto-job-applier/
│   ├── linkedin-bot/            # 2 patches allowed
│   └── Job-apply-AI-agent/
├── vault/                       # Source of truth (gitignored)
│   ├── credentials/             # Fernet-encrypted
│   ├── personas/
│   ├── learnings/              # errors.jsonl, corrections.jsonl, fixes_applied.jsonl
│   └── jobs/
├── personas/                    # Per-persona configs
├── .learnings/                 # Self-improvement log (gitignored)
│   ├── LEARNINGS.md
│   ├── ERRORS.md
│   └── FEATURE_REQUESTS.md
├── tests/
│   ├── test_vault.py
│   ├── test_self_healer.py
│   ├── test_cross_platform.py
│   ├── test_lazibrain.py
│   ├── test_page_agent.py      # NEW: MCP Bridge + page-agent routing
│   └── test_reactions.py
├── run.bat
├── requirements.txt
├── PLAN.md                     # This file
└── AGENTS.md
```

---

## 12. Success Metrics

| Metric | Target | How Measured |
|---|---|---|
| Self-heal rate | >60% of errors auto-fixed | `vault/learnings/fixes_applied.jsonl` count |
| Cross-platform coverage | 4 job sources + page-agent | Number of scraper adapters + Engine 6 |
| Vault coverage | 100% of credentials in vault | Audit check |
| page-agent MCP integration | LaziBrain controls browser agent | `_test_page_agent.py` |
| Test coverage | >80% of new code | pytest --cov |
| Review gate pass rate | >90% first try | CI green builds |
| E2E test count | ≥5 critical flows | `_test_e2e_chain.py` |

---

## Open Questions

1. **Google SSO** — still unresolved. Need user decision on OAuth vs Chrome session.
2. **Screen recording** — DOM event logging chosen; implementation pending.
3. **RemoteOK/Glassdoor API** — may require reverse-engineering; check ToS first.
4. **LaziBrain model** — poolside vs openai vs google? User to confirm.
5. **page-agent MCP transport** — STDIO (local dev) vs WebSocket (production)? User preference.
6. **FastMCP vs SSE** — FastMCP is newer; confirm compatibility with page-agent's MCP client version.

---

*Plan status: Draft v1.1 — Section 0 (architecture realignment) added based on alibaba/page-agent research. Phase 1 complete. Phase 2 now includes page-agent + MCP Bridge as new scope.*
