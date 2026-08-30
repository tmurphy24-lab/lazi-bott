"""
Bot runner / dispatcher for linkedin-autopilot.

Maps (persona, mode, provider, engine) → subprocess invocation.

Each engine adapter lives in app/engines/*.py and knows how to:
  1. translate the unified persona config into the engine's own format
  2. launch the engine as a subprocess with the right CLI args / env vars
  3. stream its stdout/stderr back to the caller for the GUI log panel

Hooks (per plan):
  - before_scrape(persona, config)  — plugin entry point
  - on_job(job_dict)                — filter/re-rank per job
  - on_error(exc, context)          — error escalation

Plugin convention: any .py file in plugins/ that defines functions named
before_scrape / on_job / on_error will be auto-loaded at startup.
"""

from __future__ import annotations

import importlib.util
import json
import logging
import os
import signal
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import List, Optional, Dict, Any, Callable

from .scraper import JobResult, scrape_jobs, make_driver
from .profile_store import Persona

logger = logging.getLogger(__name__)

BASE_DIR = Path(__file__).resolve().parent.parent
ENGINES_DIR = BASE_DIR / "engines"
PLUGINS_DIR = BASE_DIR / "plugins"
RUNS_DIR = BASE_DIR / "runs"
RUNS_DIR.mkdir(parents=True, exist_ok=True)


# --- plugin loader (minimal: no daemon, no dynamic discovery magic) ---

def load_plugins() -> List[Dict[str, Callable]]:
    """
    Load any .py file in plugins/ that exports hook functions.
    Returns a list of dicts: {"before_scrape": fn, "on_job": fn, "on_error": fn}.
    """
    plugins = []
    if not PLUGINS_DIR.exists():
        return plugins
    for py_file in PLUGINS_DIR.glob("*.py"):
        if py_file.name == "__init__.py":
            continue
        # controlled import (no exec) for security
        try:
            spec = importlib.util.spec_from_file_location(f"plugin_{py_file.stem}", py_file)
            if not spec or not spec.loader:
                continue
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)
            hooks = {
                name: getattr(mod, name)
                for name in ("before_scrape", "on_job", "on_error")
                if hasattr(mod, name)
            }
            if hooks:
                plugins.append(hooks)
                logger.info("Loaded plugin: %s", py_file.stem)
        except Exception as e:
            logger.warning("Failed to load plugin %s: %s", py_file.name, e)
    return plugins


def _call_hook(plugins: List[Dict], hook_name: str, *args, **kwargs):
    for p in plugins:
        fn = p.get(hook_name)
        if fn:
            try:
                fn(*args, **kwargs)
            except Exception as e:
                logger.warning("Plugin %s hook failed: %s", hook_name, e)


# --- the engines dict ---

# Each adapter module exposes:
#   - name (str)
#   - description (str)
#   - invoke(persona: Persona, provider: str, config: dict, driver_profile: str,
#           mode: str, max_jobs: int) -> subprocess.Popen
#   - get_env(provider: str) -> dict   (env vars to inject)

from .engines.easyapplyjobsbot_adapter import EasyApplyJobsBotAdapter
from .engines.linkedin_aihawk_adapter import LinkedInAIHawkAdapter
from .engines.auto_job_applier_adapter import AutoJobApplierAdapter
from .engines.linkedin_bot_adapter import LinkedInBotAdapter
from .engines.job_apply_ai_agent_adapter import JobApplyAIAgentAdapter

ENGINES: Dict[str, Any] = {
    "easyapplyjobsbot": EasyApplyJobsBotAdapter,
    "linkedin-aihawk": LinkedInAIHawkAdapter,
    "auto-job-applier": AutoJobApplierAdapter,
    "linkedin-bot": LinkedInBotAdapter,
    "job-apply-ai-agent": JobApplyAIAgentAdapter,
}

# which engines are "auto-apply" vs "scrape only"
AUTO_APPLY_ENGINES = {"easyapplyjobsbot", "linkedin-aihawk", "auto-job-applier", "linkedin-bot"}
SCRAPE_ONLY_ENGINES = {"job-apply-ai-agent"}


class RunResult:
    """Outcome of a single engine run."""

    def __init__(self):
        self.jobs_found = 0
        self.jobs_applied = 0
        self.jobs_skipped = 0
        self.jobs_failed = 0
        self.errors: List[str] = []
        self.start_time: float = 0
        self.end_time: float = 0
        self.engine: str = ""
        self.persona: str = ""
        self.provider: str = ""

    def to_dict(self) -> dict:
        return {
            "engine": self.engine,
            "persona": self.persona,
            "provider": self.provider,
            "jobs_found": self.jobs_found,
            "jobs_applied": self.jobs_applied,
            "jobs_skipped": self.jobs_skipped,
            "jobs_failed": self.jobs_failed,
            "errors": self.errors,
            "duration_seconds": round(self.end_time - self.start_time, 1) if self.end_time else 0,
        }

    def save(self):
        ts = time.strftime("%Y%m%d-%H%M%S")
        path = RUNS_DIR / f"{ts}-{self.persona}-{self.engine}.json"
        with open(path, "w") as f:
            json.dump(self.to_dict(), f, indent=2)
        logger.info("Run summary saved to %s", path)
        return path


# --- driver management ---

_driver_lock = threading.Lock()
_shared_driver = None


def get_shared_driver(persona: Persona, headless: bool = False):
    """Return a shared Chrome driver for the persona's browser profile."""
    global _shared_driver
    with _driver_lock:
        if _shared_driver is None:
            profile = str(persona.browser_profile)
            _shared_driver = make_driver(user_data_dir=profile, headless=headless)
    return _shared_driver


def release_driver():
    global _shared_driver
    if _shared_driver is not None:
        _shared_driver.quit()
        _shared_driver = None


# --- the main orchestrator ---

def run(
    persona_name: str,
    engine_name: str,
    provider: str = "none",       # "poolside" | "openai" | "google" | "none"
    mode: str = "auto-apply",     # "scrape" | "auto-apply"
    max_jobs: int = 25,
    headless: bool = False,
    log_callback: Optional[Callable[[str], None]] = None,
) -> RunResult:
    """
    Main entry: scrape jobs via the shared scraper, then dispatch to the
    selected engine for either applying or (scrape-only) saving to Excel.
    """
    persona = Persona(persona_name)
    config = persona.load_config()
    result = RunResult()
    result.persona = persona_name
    result.engine = engine_name
    result.provider = provider
    result.start_time = time.time()

    plugins = load_plugins()

    # Built-in default on_job filter: blacklist companies/titles from persona config
    from .auto_filler import make_on_job_filter
    plugins.append({"on_job": make_on_job_filter(persona)})

    _call_hook(plugins, "before_scrape", persona=persona, config=config)

    # --- Step 1: shared scraper discovers jobs ---
    driver = get_shared_driver(persona, headless=headless)
    jobs: List[JobResult] = []
    try:
        jobs = scrape_jobs(
            driver,
            positions=config["titles"],
            location=config["location"],
            max_jobs=max_jobs,
            salary_min=config.get("salary_min"),
        )
        result.jobs_found = len(jobs)
        logger.info("Scraper found %d jobs", len(jobs))
        if log_callback:
            log_callback(f"[scraper] Found {len(jobs)} jobs for persona '{persona_name}'")
    except Exception as e:
        logger.error("Scraper failed: %s", e)
        result.errors.append(f"scraper: {e}")
        _call_hook(plugins, "on_error", exc=e, context="scraper")
        driver.quit()
        result.end_time = time.time()
        result.save()
        return result
    finally:
        release_driver()

    # --- Step 2: filter via on_job hook ---
    filtered_jobs = []
    for job in jobs:
        skip = False
        for p in plugins:
            if "on_job" in p:
                try:
                    if not p["on_job"](job.to_dict()):
                        skip = True
                        break
                except Exception as e:
                    logger.warning("on_job hook failed: %s", e)
        if not skip:
            filtered_jobs.append(job)
    if len(filtered_jobs) < len(jobs):
        logger.info("on_job hook filtered %d jobs", len(jobs) - len(filtered_jobs))
        jobs = filtered_jobs

    if not jobs:
        result.errors.append("scraper returned 0 jobs after filtering")
        result.end_time = time.time()
        result.save()
        return result

    # --- Step 3: dispatch to engine ---
    adapter_cls = ENGINES.get(engine_name)
    if adapter_cls is None:
        raise ValueError(f"Unknown engine: {engine_name}")

    adapter = adapter_cls()
    if mode == "scrape" and engine_name in AUTO_APPLY_ENGINES:
        # For scrape-only with an auto-apply engine, just save job list, don't apply
        logger.info("Scrape-only mode: saving job list, not applying")
        if log_callback:
            log_callback("[scrape-only] Saving job list without applying")
        result.jobs_skipped = len(jobs)
        result.end_time = time.time()
        result.save()
        return result

    env = adapter.get_env(provider)
    try:
        proc = adapter.invoke(
            persona=persona,
            config=config,
            jobs=jobs,
            provider=provider,
            max_jobs=max_jobs,
            env=env,
            log_callback=log_callback,
        )
        # wait for completion (or the caller can poll)
        proc.wait()
        result.jobs_applied = getattr(adapter, "applied_count", 0)
        result.jobs_failed = getattr(adapter, "failed_count", 0)
        result.jobs_skipped = max(0, len(jobs) - result.jobs_applied - result.jobs_failed)

        # F1: auto-record every successfully applied job to the JobTracker
        try:
            from .job_tracker import record_application
            for i in range(result.jobs_applied):
                if i < len(jobs):
                    record_application(
                        persona=persona_name,
                        job=jobs[i].to_dict(),
                        status="applied",
                        engine=engine_name,
                    )
        except Exception as e:
            logger.warning("Failed to record applications: %s", e)
    except Exception as e:
        logger.error("Engine %s failed: %s", engine_name, e)
        result.errors.append(f"engine {engine_name}: {e}")
        _call_hook(plugins, "on_error", exc=e, context=engine_name)
    finally:
        result.end_time = time.time()
        result.save()

    return result
