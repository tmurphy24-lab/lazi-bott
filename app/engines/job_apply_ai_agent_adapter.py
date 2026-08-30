"""
Adapter for Job-apply-AI-agent.
This bot is scraper-only — it scrapes + tailors CVs, does not auto-apply.
We invoke its existing CLI: job-apply-ai scrape / tailor / batch.
"""

from __future__ import annotations
import logging, os, re, subprocess, threading
from pathlib import Path
from typing import List, Dict, Any, Optional, Callable

logger = logging.getLogger(__name__)

ENGINES_DIR = Path(__file__).resolve().parent.parent.parent / "engines"
JOBAPPLY_DIR = ENGINES_DIR / "Job-apply-AI-agent"


class JobApplyAIAgentAdapter:
    name = "job-apply-ai-agent"
    description = "Scrape + CV tailor — no auto-apply (local spaCy, no API key)"

    def __init__(self):
        self.applied_count = 0  # scrape-only; never auto-applies
        self.failed_count = 0

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
        query = config["titles"][0]

        cmd = [
            env.get("PYTHON", "python"), "-u", "-m", "job_apply_ai",
            "scrape",
            "--keyword", query,
            "--location", config["location"],
            "--max-jobs", str(max_jobs),
        ]
        if log_callback:
            log_callback(f"[job-apply-ai-agent] Launching: {' '.join(cmd)}")

        proc = subprocess.Popen(
            cmd,
            cwd=str(JOBAPPLY_DIR),
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
        )

        scraped_re = re.compile(r"(Successfully scraped|saved to)", re.IGNORECASE)
        failed_re = re.compile(r"(error|exception|failed)", re.IGNORECASE)

        def _stream():
            try:
                for line in proc.stdout:
                    if scraped_re.search(line):
                        self.applied_count += 1  # treating as "completed" for scrape-only
                    elif failed_re.search(line):
                        self.failed_count += 1
                    if log_callback:
                        log_callback(f"  {line.rstrip()}")
            except Exception:
                pass

        t = threading.Thread(target=_stream, daemon=True)
        t.start()
        return proc
