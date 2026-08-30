"""
Adapter for linkedin-aihawk.
Writes work_preferences.yaml from the unified persona config, then launches
linkedin-aihawk/main.py as a subprocess.
"""

from __future__ import annotations
import logging, os, re, subprocess, threading
from pathlib import Path
from typing import List, Dict, Any, Optional, Callable

import yaml

logger = logging.getLogger(__name__)

ENGINES_DIR = Path(__file__).resolve().parent.parent.parent / "engines"
AIHAWK_DIR = ENGINES_DIR / "linkedin-aihawk"


class LinkedInAIHawkAdapter:
    name = "linkedin-aihawk"
    description = "Selenium Easy Apply — YAML resume-based answers, no LLM"

    def __init__(self):
        self.applied_count = 0
        self.failed_count = 0

    def _write_work_preferences(self, cfg: dict, target_dir: Path) -> Path:
        """Write work_preferences.yaml from the unified config."""
        wp = {
            "remote": True,
            "hybrid": True,
            "onsite": True,
            "experience_level": {
                "internship": False,
                "entry": False,
                "associate": False,
                "mid_senior_level": "Mid-Senior level" in cfg.get("experience_levels", []),
                "director": "Director" in cfg.get("experience_levels", []),
                "executive": False,
            },
            "job_types": {
                "full_time": "Full-time" in cfg.get("job_types", []),
                "contract": "Contract" in cfg.get("job_types", []),
                "part_time": "Part-time" in cfg.get("job_types", []),
                "temporary": "Temporary" in cfg.get("job_types", []),
                "internship": False,
                "other": False,
                "volunteer": False,
            },
            "date": {
                "all_time": False,
                "month": False,
                "week": True,
                "24_hours": False,
            },
            "positions": cfg["titles"],
            "locations": [cfg["location"]] if cfg["location"] != "United States" else ["United States"],
            "apply_once_at_company": cfg.get("apply_once_at_company", True),
            "distance": 100,
            "company_blacklist": cfg["blacklist_companies"],
            "title_blacklist": cfg["blacklist_titles"],
            "location_blacklist": [],
        }
        target = target_dir / "data_folder" / "work_preferences.yaml"
        target.parent.mkdir(parents=True, exist_ok=True)
        with open(target, "w", encoding="utf-8") as f:
            yaml.dump(wp, f, sort_keys=False, allow_unicode=True)
        return target

    def get_env(self, provider: str) -> dict:
        env = os.environ.copy()
        return env

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
        self._write_work_preferences(config, AIHAWK_DIR)

        cmd = [
            env.get("PYTHON", "python"), "-u",
            "-m", "main",
        ]
        if log_callback:
            log_callback(f"[linkedin-aihawk] Launching: {' '.join(cmd)}")

        proc = subprocess.Popen(
            cmd,
            cwd=str(AIHAWK_DIR),
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
        )

        applied_re = re.compile(r"(applied successfully|submitting application|applied to)", re.IGNORECASE)
        failed_re = re.compile(r"(failed|skipped|error|exception|cannot apply)", re.IGNORECASE)

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
