"""
Adapter for linkedin-bot (lukerbs).
Patches the OpenAI base_url via env var and feeds the job query via CLI arg
instead of the tkinter prompt.
"""

from __future__ import annotations
import logging, os, re, subprocess, threading
from pathlib import Path
from typing import List, Dict, Any, Optional, Callable

logger = logging.getLogger(__name__)

ENGINES_DIR = Path(__file__).resolve().parent.parent.parent / "engines"
LINKEDIN_BOT_DIR = ENGINES_DIR / "linkedin-bot"


class LinkedInBotAdapter:
    name = "linkedin-bot"
    description = "Selenium Easy Apply — OpenAI/Gemini question answering"

    def __init__(self):
        self.applied_count = 0
        self.failed_count = 0

    def get_env(self, provider: str) -> dict:
        env = os.environ.copy()
        from ..profile_store import resolve_api_key

        if provider == "poolside":
            key = resolve_api_key("poolside")
            env["OPENAI_API_BASE_URL"] = "https://inference.poolside.ai/v1"
            env["OPENAI_API_KEY"] = key or ""
        elif provider == "openai":
            key = resolve_api_key("openai")
            env["OPENAI_API_BASE_URL"] = "https://api.openai.com/v1"
            env["OPENAI_API_KEY"] = key or ""
        else:
            env["OPENAI_API_BASE_URL"] = ""
            env["OPENAI_API_KEY"] = ""
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
        query = config["titles"][0]

        cmd = [
            env.get("PYTHON", "python"), "-u",
            str(LINKEDIN_BOT_DIR / "easy_apply.py"),
            "--jobs", query,
            "--salary", str(config.get("salary_min", 120000)),
        ]
        if log_callback:
            log_callback(f"[linkedin-bot] Launching: {' '.join(cmd)}")

        proc = subprocess.Popen(
            cmd,
            cwd=str(LINKEDIN_BOT_DIR),
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
        )

        applied_re = re.compile(r"(Application submitted successfully|Your application has successfully)", re.IGNORECASE)
        failed_re = re.compile(r"(Failed|Discarding application|ERROR)", re.IGNORECASE)

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
