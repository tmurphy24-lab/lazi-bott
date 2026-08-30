"""
Profile store for linkedin-autopilot.

Per-persona configuration lives in linkedin-autopilot/personas/<name>/:
  search_config.yaml   -> titles, salary range, experience years, blacklist
  profile.yaml         -> personal info, resume path, skills
  browser_profile/     -> Chrome user-data-dir

API keys stored via keyring (Windows Credential Manager) or keys/<provider>.key.

NEW (2026-08-30):
  - Range parameters (salary_min, salary_max, experience_years_min/max)
  - Blacklist add/remove API
  - profile.yaml schema (personal_info, resume, skills, experience)
  - ensure_profile() bootstrap
"""

from __future__ import annotations

import json
import os
import logging
import keyring
from pathlib import Path
from typing import Optional, Dict, Any, List
import yaml

logger = logging.getLogger(__name__)

BASE_DIR = Path(__file__).resolve().parent.parent  # linkedin-autopilot/
PERSONAS_DIR = BASE_DIR / "personas"
KEYS_DIR = BASE_DIR / "keys"

KEYRING_APP = "linkedin-autopilot"

# === Centralized parameter schema (used by GUI + auto-filler) ===
# Each entry: (key, type, default, min, max, step, label, group)
PARAM_SCHEMA: List[Dict[str, Any]] = [
    {"key": "salary_min",          "type": "int",  "default": 120000, "min": 0,      "max": 500000, "step": 5000,   "label": "Salary Min ($)",          "group": "Search"},
    {"key": "salary_max",          "type": "int",  "default": 250000, "min": 0,      "max": 500000, "step": 5000,   "label": "Salary Max ($)",          "group": "Search"},
    {"key": "experience_years_min","type": "int",  "default": 5,      "min": 0,      "max": 30,     "step": 1,      "label": "Experience Min (years)",  "group": "Search"},
    {"key": "experience_years_max","type": "int",  "default": 20,     "min": 0,      "max": 30,     "step": 1,      "label": "Experience Max (years)",  "group": "Search"},
    {"key": "max_applications",    "type": "int",  "default": 50,     "min": 1,      "max": 500,    "step": 5,      "label": "Max Applications/Run",   "group": "Run"},
    {"key": "date_posted",         "type": "str",  "default": "Past Week", "options": ["Any Time","Past 24 hours","Past Week","Past Month"], "label": "Date Posted", "group": "Search"},
    {"key": "remote",              "type": "bool", "default": True,   "label": "Include Remote",          "group": "Search"},
    {"key": "hybrid",              "type": "bool", "default": True,   "label": "Include Hybrid",          "group": "Search"},
    {"key": "onsite",              "type": "bool", "default": True,   "label": "Include Onsite",         "group": "Search"},
    {"key": "apply_once_at_company","type":"bool", "default": True,   "label": "Apply Once Per Company",  "group": "Run"},
]


class Persona:
    """Thin wrapper around a persona directory on disk."""

    def __init__(self, name: str):
        self.name = name
        self.dir = PERSONAS_DIR / name
        self.browser_profile = self.dir / "browser_profile"
        self.config_path = self.dir / "search_config.yaml"
        self.profile_path = self.dir / "profile.yaml"
        self.resume_path = self.dir / "resume.txt"

    @property
    def exists(self) -> bool:
        return self.config_path.is_file()

    def ensure_dirs(self):
        self.dir.mkdir(parents=True, exist_ok=True)
        self.browser_profile.mkdir(parents=True, exist_ok=True)

    def load_config(self) -> Dict[str, Any]:
        """Load search_config.yaml, returning a dict with sensible defaults."""
        defaults = {
            "titles": [],
            "location": "United States",
            "salary_min": 120000,
            "salary_max": 250000,
            "experience_years_min": 5,
            "experience_years_max": 20,
            "experience_levels": ["Mid-Senior level", "Director"],
            "job_types": ["Full-time", "Part-time"],
            "date_posted": "Past Week",
            "remote": True,
            "hybrid": True,
            "onsite": True,
            "blacklist_companies": [],
            "blacklist_titles": [],
            "apply_once_at_company": True,
            "max_applications": 50,
        }
        if self.config_path.exists():
            with open(self.config_path, "r", encoding="utf-8") as f:
                user_cfg = yaml.safe_load(f) or {}
            defaults.update(user_cfg)
        return defaults

    def save_config(self, cfg: Dict[str, Any]):
        self.ensure_dirs()
        with open(self.config_path, "w", encoding="utf-8") as f:
            yaml.dump(cfg, f, sort_keys=False, allow_unicode=True)

    def update_config(self, **kwargs) -> Dict[str, Any]:
        """Merge kwargs into saved config and return the full config."""
        cfg = self.load_config()
        cfg.update(kwargs)
        self.save_config(cfg)
        return cfg

    def load_profile(self) -> Dict[str, Any]:
        """Load profile.yaml: personal info, resume path, skills, experience."""
        defaults = {
            "personal_info": {
                "first_name": "",
                "last_name": "",
                "email": "",
                "phone": "",
                "linkedin_url": "",
                "city": "",
                "state": "",
                "country": "United States",
            },
            "resume_path": "",
            "skills": [],
            "experience": [],   # list of {title, company, start, end, summary}
            "education": [],    # list of {degree, school, year}
            "blacklist_companies": [],
            "blacklist_titles": [],
        }
        if self.profile_path.exists():
            with open(self.profile_path, "r", encoding="utf-8") as f:
                user = yaml.safe_load(f) or {}
            # deep-merge personal_info
            pi = defaults["personal_info"].copy()
            pi.update(user.get("personal_info", {}) or {})
            user["personal_info"] = pi
            defaults.update(user)
        return defaults

    def save_profile(self, profile: Dict[str, Any]):
        self.ensure_dirs()
        with open(self.profile_path, "w", encoding="utf-8") as f:
            yaml.dump(profile, f, sort_keys=False, allow_unicode=True)

    def update_profile(self, **kwargs) -> Dict[str, Any]:
        profile = self.load_profile()
        profile.update(kwargs)
        self.save_profile(profile)
        return profile

    def has_browser_profile(self) -> bool:
        if not self.browser_profile.exists():
            return False
        return any(p.is_dir() for p in self.browser_profile.iterdir())

    # --- blacklist helpers (called by GUI add/remove) ---
    def add_blacklist_company(self, company: str) -> List[str]:
        cfg = self.load_config()
        if company not in cfg["blacklist_companies"]:
            cfg["blacklist_companies"].append(company)
            self.save_config(cfg)
        return cfg["blacklist_companies"]

    def remove_blacklist_company(self, company: str) -> List[str]:
        cfg = self.load_config()
        if company in cfg["blacklist_companies"]:
            cfg["blacklist_companies"].remove(company)
            self.save_config(cfg)
        return cfg["blacklist_companies"]

    def add_blacklist_title(self, title: str) -> List[str]:
        cfg = self.load_config()
        if title not in cfg["blacklist_titles"]:
            cfg["blacklist_titles"].append(title)
            self.save_config(cfg)
        return cfg["blacklist_titles"]

    def remove_blacklist_title(self, title: str) -> List[str]:
        cfg = self.load_config()
        if title in cfg["blacklist_titles"]:
            cfg["blacklist_titles"].remove(title)
            self.save_config(cfg)
        return cfg["blacklist_titles"]


def list_personas() -> List[str]:
    if not PERSONAS_DIR.exists():
        return []
    return [d.name for d in PERSONAS_DIR.iterdir() if d.is_dir()]


# --- API key storage ---

def store_api_key(provider: str, key_value: str) -> None:
    keyring.set_password(KEYRING_APP, provider, key_value)
    logger.info("API key for %s stored in credential manager", provider)


def get_api_key(provider: str) -> Optional[str]:
    return keyring.get_password(KEYRING_APP, provider)


def delete_api_key(provider: str) -> None:
    keyring.delete_password(KEYRING_APP, provider)


def get_api_key_file(provider: str) -> Optional[str]:
    candidate = KEYS_DIR / f"{provider}.key"
    if candidate.exists():
        return candidate.read_text(encoding="utf-8").strip()
    return None


def resolve_api_key(provider: str) -> Optional[str]:
    key = get_api_key(provider)
    if not key:
        key = get_api_key_file(provider)
    return key


# --- persona bootstrap ---

DEFAULT_PERSONA_CONFIGS = {
    "supply-chain-exec": {
        "titles": [
            "Director of Supply Chain", "Supply Chain Director", "VP Supply Chain",
            "Head of Supply Chain", "Senior Supply Chain Manager", "Global Supply Chain Manager",
            "Director of Operations", "Director of Logistics", "Head of Planning", "Director of Planning",
        ],
        "location": "United States",
        "salary_min": 120000,
        "salary_max": 250000,
        "experience_years_min": 10,
        "experience_years_max": 25,
        "experience_levels": ["Mid-Senior level", "Director"],
        "job_types": ["Full-time", "Part-time"],
        "date_posted": "Past Week",
        "blacklist_companies": [
            "Crossover", "Jobot", "Dice", "Insight Global", "TEKsystems",
            "Aerotek", "Randstad", "Adecco", "Kforce", "Motion Recruitment",
            "Cynet", "Artech", "Collabera",
        ],
        "blacklist_titles": [
            "Junior", "Entry Level", "Intern", "Coordinator", "Assistant",
            "Apprentice", "Clerk", "Technician", "Driver", "CDL",
            "Software", "Developer", "Frontend", "Full Stack",
            "Recruiter", "Sales Representative", "Nurse", "Teacher",
        ],
        "apply_once_at_company": True,
        "max_applications": 50,
    },
    "procurement": {
        "titles": [
            "Director of Procurement", "Head of Procurement", "Senior Procurement Manager",
            "Strategic Sourcing Manager", "Category Manager", "Supplier Fulfillment Manager",
            "Materials Manager", "Supplier Performance Manager", "Purchasing Manager",
            "Head of Supplier Management",
        ],
        "location": "United States",
        "salary_min": 120000,
        "salary_max": 250000,
        "experience_years_min": 10,
        "experience_years_max": 25,
        "experience_levels": ["Mid-Senior level", "Director"],
        "job_types": ["Full-time", "Part-time"],
        "date_posted": "Past Week",
        "blacklist_companies": [
            "Crossover", "Jobot", "Dice", "Insight Global", "TEKsystems",
            "Aerotek", "Randstad", "Adecco", "Kforce", "Motion Recruitment",
            "Cynet", "Artech", "Collabera",
        ],
        "blacklist_titles": [
            "Junior", "Entry Level", "Intern", "Coordinator", "Assistant",
            "Apprentice", "Clerk", "Technician", "Driver", "CDL",
            "Software", "Developer", "Frontend", "Full Stack",
            "Recruiter", "Sales Representative", "Nurse", "Teacher",
        ],
        "apply_once_at_company": True,
        "max_applications": 50,
    },
}


def ensure_persona(persona_name: str) -> Persona:
    """Create persona dir + default search_config.yaml + profile.yaml if missing."""
    p = Persona(persona_name)
    if not p.exists:
        p.ensure_dirs()
        defaults = DEFAULT_PERSONA_CONFIGS.get(
            persona_name, DEFAULT_PERSONA_CONFIGS["supply-chain-exec"]
        )
        p.save_config(defaults)
        logger.info("Created persona '%s' with default config", persona_name)
    # always ensure profile.yaml exists
    if not p.profile_path.exists():
        p.save_profile(p.load_profile())
    return p
