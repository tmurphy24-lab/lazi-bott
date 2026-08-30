"""
Adapter for EasyApplyJobsBot.
Writes config.py fields from the unified persona config, then launches
EasyApplyJobsBot/linkedin.py as a subprocess.

FIXED (linkedin-autopilot review 2026-08-30):
  Previously this wrote to `config_autopilot.py`, but `linkedin.py` and
  `utils.py` both `import config` (not config_autopilot). Overrides were
  silently dropped. Now we preserve the original config.py in config.py.bak
  and write the merged overrides directly into config.py. The engine copy in
  engines/EasyApplyJobsBot/ is owned by linkedin-autopilot (the originals at
  C:\\Users\\trevo\\Desktop\\.agents\\EasyApplyJobsBot\\ are NOT modified), so
  in-place mutation is safe.
"""

from __future__ import annotations
import logging, os, shutil, subprocess, threading
from pathlib import Path
from typing import List, Dict, Any, Optional, Callable

logger = logging.getLogger(__name__)

ENGINES_DIR = Path(__file__).resolve().parent.parent.parent / "engines"
EASYAPPLY_DIR = ENGINES_DIR / "EasyApplyJobsBot"
BACKUP_PATH = EASYAPPLY_DIR / "config.py.bak"


class EasyApplyJobsBotAdapter:
    name = "EasyApplyJobsBot"
    description = "Selenium Easy Apply — form filling only, no AI"

    def __init__(self):
        self.applied_count = 0
        self.failed_count = 0

    def _write_config(self, cfg: dict, target_dir: Path) -> Path:
        """
        Write merged persona config into config.py. Backup the original to
        config.py.bak on first write so the user can restore if needed.
        """
        config_path = target_dir / "config.py"

        # First-time backup of the pristine engine config (only once, only if no backup exists)
        if config_path.exists() and not BACKUP_PATH.exists():
            shutil.copy2(config_path, BACKUP_PATH)
            logger.info("Backed up original config.py -> config.py.bak")

        orig_text = config_path.read_text(encoding="utf-8") if config_path.exists() else ""

        overrides = {
            "keywords": cfg["titles"],
            "experienceLevels": cfg["experience_levels"],
            "salary": [f"${cfg['salary_min']:,}+"] if cfg.get("salary_min") else ['"$120,000+"'],
            "jobType": cfg["job_types"],
            "location": [cfg["location"]] if cfg["location"] != "United States" else ["NorthAmerica"],
            "blacklistCompanies": cfg["blacklist_companies"],
            "blackListTitles": cfg["blacklist_titles"],
            "datePosted": [cfg.get("date_posted", "Past Week")],
            "maxApplicationsPerRun": cfg.get("max_applications", 50),
        }

        override_lines = "\n".join(f"{k} = {v!r}" for k, v in overrides.items())
        full_config = (
            f"# --- AUTO-WRITTEN by linkedin-autopilot ---\n"
            f"# Persona: {cfg.get('persona_name','')}\n"
            f"# Original preserved at: config.py.bak\n"
            f"{override_lines}\n\n"
            f"# --- original config.py below ---\n{orig_text}"
        )

        config_path.write_text(full_config, encoding="utf-8")
        return config_path

    def get_env(self, provider: str) -> dict:
        """No AI provider needed for this bot."""
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
        target_dir = EASYAPPLY_DIR
        self._write_config(config, target_dir)

        cmd = [
            env.get("PYTHON", "python"), "-u",
            str(target_dir / "linkedin.py"),
        ]
        if log_callback:
            log_callback(f"[EasyApplyJobsBot] Launching: {' '.join(cmd)}")

        proc = subprocess.Popen(
            cmd,
            cwd=str(target_dir),
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
        )

        # Stream stdout, also track applied/failed counts
        import re
        applied_re = re.compile(r"(Just Applied|DRY RUN - Would apply)", re.IGNORECASE)
        failed_re = re.compile(r"(Cannot apply|Blacklisted Job)", re.IGNORECASE)

        def _stream():
            try:
                for line in proc.stdout:
                    if applied_re.search(line):
                        self.applied_count += 1
                    if failed_re.search(line):
                        self.failed_count += 1
                    if log_callback:
                        log_callback(f"  {line.rstrip()}")
            except Exception:
                pass

        t = threading.Thread(target=_stream, daemon=True)
        t.start()
        return proc
