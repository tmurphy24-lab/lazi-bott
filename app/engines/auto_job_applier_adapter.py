"""
Adapter for auto-job-applier (GodsScion/Auto_job_applier_linkedIn).

FIXED (linkedin-autopilot review 2026-08-30):
  Previously wrote to `config/search_autopilot.py`, but `runAiBot.py` does
  `from config.search import *` — overrides were never loaded. The engine
  already has a built-in override mechanism (`config/_overrides.py` reads
  `user_config.json` at the project root). Now we write a `user_config.json`
  with a `"search"` section, using the bot's own loader. Zero engine patching.
"""

from __future__ import annotations
import json
import logging, os, subprocess, threading
from pathlib import Path
from typing import List, Dict, Any, Optional, Callable

logger = logging.getLogger(__name__)

ENGINES_DIR = Path(__file__).resolve().parent.parent.parent / "engines"
AUTOJOB_DIR = ENGINES_DIR / "auto-job-applier"
USER_CONFIG_PATH = AUTOJOB_DIR / "user_config.json"


class AutoJobApplierAdapter:
    name = "auto-job-applier"
    description = "Selenium Easy Apply — GodsScion engine"

    def __init__(self):
        self.applied_count = 0
        self.failed_count = 0

    def _write_user_config(self, cfg: dict, target_dir: Path) -> Path:
        """
        Write a user_config.json with a "search" section. The engine's own
        _overrides.py loads this and applies matching keys to config.search.
        """
        salary_str = f"${cfg.get('salary_min', 120000):,}+"
        search_section = {
            "search_terms": cfg["titles"],
            "search_location": cfg["location"],
            "salary": salary_str,
            "experience_level": cfg["experience_levels"],
            "date_posted": cfg.get("date_posted", "Past week"),
            "easy_apply_only": True,
            "sort_by": "Most recent",
        }
        payload = {"search": search_section}
        USER_CONFIG_PATH.write_text(
            json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8"
        )
        logger.info("Wrote user_config.json -> %s", USER_CONFIG_PATH)
        return USER_CONFIG_PATH

    def get_env(self, provider: str) -> dict:
        return os.environ.copy()

    def invoke(
        self,
        persona,
        config: dict,
        jobs: List,
        provider: str,
        max_jobs: int,
        env: dict,
        log_callback: Optional[Callable[[str], None]] = None,
    ) -> subprocess.Popen:
        self._write_user_config(config, AUTOJOB_DIR)

        cmd = [
            env.get("PYTHON", "python"), "-u",
            str(AUTOJOB_DIR / "runAiBot.py"),
        ]
        if log_callback:
            log_callback(f"[auto-job-applier] Launching: {' '.join(cmd)}")

        proc = subprocess.Popen(
            cmd,
            cwd=str(AUTOJOB_DIR),
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
        )

        import re
        applied_re = re.compile(r"(applied|successful|submitting)", re.IGNORECASE)
        failed_re = re.compile(r"(failed|error|skip|exception)", re.IGNORECASE)

        def _stream():
            try:
                for line in proc.stdout:
                    if applied_re.search(line):
                        self.applied_count += 1
                    elif failed_re.search(line):
                        self.failed_count += 1
                    if log_callback:
                        log_callback(f"  {line.rstrip()}")
            except Exception:
                pass

        t = threading.Thread(target=_stream, daemon=True)
        t.start()
        return proc
