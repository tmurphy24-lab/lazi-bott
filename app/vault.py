"""
Lazi Vault — source of truth for linkedin-autopilot.

Directory structure (all under vault/ — gitignored):
    vault/
    ├── credentials/         ← Fernet-encrypted (per persona)
    │   └── {persona}/
    │       ├── credentials.vault    # LinkedIn session, site passwords
    │       └── api_keys.vault        # per-provider API keys
    ├── personas/           ← mirrors personas/ but is the runtime source of truth
    ├── learnings/         ← append-only structured logs
    │   ├── errors.jsonl            # every engine failure
    │   ├── corrections.jsonl        # user corrections to Lazi
    │   └── fixes_applied.jsonl     # self-heal actions taken
    └── jobs/             ← cross-platform job cache
        └── {persona}/
            └── jobs.jsonl

Public API:
    Vault()                    — single shared instance
    vault.store_credential(persona, key, value)
    vault.get_credential(persona, key) -> Optional[str]
    vault.log_error(engine, error, context)
    vault.log_correction(original, corrected, reason)
    vault.log_fix(engine, error, fix_description, applied)
    vault.get_persona_config(persona) -> dict
    vault.save_persona_config(persona, config)
    vault.cache_job(persona, job)
    vault.get_cached_jobs(persona, query, location) -> List[dict]
"""

from __future__ import annotations

import json
import logging
import os
import uuid
from dataclasses import dataclass, asdict, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, Dict, Any, List

import keyring
from cryptography.fernet import Fernet, InvalidToken

logger = logging.getLogger(__name__)

# === Paths ===

BASE_DIR = Path(__file__).resolve().parent.parent  # linkedin-autopilot/
VAULT_DIR = BASE_DIR / "vault"
CREDENTIALS_DIR = VAULT_DIR / "credentials"
LEARNINGS_DIR = VAULT_DIR / "learnings"
JOBS_DIR = VAULT_DIR / "jobs"

KEYRING_APP = "lazi-bot-vault"
KEYRING_VAULT_KEY = "lazi_vault_key"

# === Fernet key management ===

def _get_or_create_vault_key() -> bytes:
    """Get the Fernet key from keyring, or generate and store a new one."""
    existing = keyring.get_password(KEYRING_APP, KEYRING_VAULT_KEY)
    if existing:
        return existing.encode("utf-8")
    new_key = Fernet.generate_key()
    keyring.set_password(KEYRING_APP, KEYRING_VAULT_KEY, new_key.decode("utf-8"))
    logger.info("New Lazi Vault key generated and stored in OS credential manager")
    return new_key


def _fernet() -> Fernet:
    return Fernet(_get_or_create_vault_key())


# === Vault init ===

def _ensure_dirs() -> None:
    for d in (CREDENTIALS_DIR, LEARNINGS_DIR, JOBS_DIR):
        d.mkdir(parents=True, exist_ok=True)


# === Credential vault ===

def _credential_path(persona: str, name: str) -> Path:
    p = CREDENTIALS_DIR / persona
    p.mkdir(parents=True, exist_ok=True)
    return p / f"{name}.vault"


def _read_credential_vault(persona: str, name: str) -> Dict[str, Any]:
    path = _credential_path(persona, name)
    if not path.exists():
        return {}
    try:
        raw = path.read_bytes()
        decrypted = _fernet().decrypt(raw)
        return json.loads(decrypted.decode("utf-8"))
    except (InvalidToken, json.JSONDecodeError, OSError) as e:
        logger.error("Credential vault read failed for %s/%s: %s", persona, name, e)
        return {}


def _write_credential_vault(persona: str, name: str, data: Dict[str, Any]) -> None:
    path = _credential_path(persona, name)
    payload = json.dumps(data, indent=2, ensure_ascii=False).encode("utf-8")
    encrypted = _fernet().encrypt(payload)
    path.write_bytes(encrypted)
    logger.debug("Vault written: %s/%s (%d entries)", persona, name, len(data))


def store_credential(persona: str, key: str, value: str, vault: str = "credentials") -> None:
    """Store an encrypted credential for a persona."""
    _ensure_dirs()
    data = _read_credential_vault(persona, vault)
    data[key] = value
    _write_credential_vault(persona, vault, data)


def get_credential(persona: str, key: str, vault: str = "credentials") -> Optional[str]:
    """Retrieve an encrypted credential for a persona."""
    data = _read_credential_vault(persona, vault)
    return data.get(key)


def list_credentials(persona: str, vault: str = "credentials") -> List[str]:
    """List all credential keys for a persona."""
    return sorted(_read_credential_vault(persona, vault).keys())


def delete_credential(persona: str, key: str, vault: str = "credentials") -> bool:
    """Remove a credential. Returns True if it existed."""
    data = _read_credential_vault(persona, vault)
    if key in data:
        del data[key]
        _write_credential_vault(persona, vault, data)
        return True
    return False


# === Learnings: append-only structured logs ===

@dataclass
class ErrorEntry:
    id: str
    timestamp: str
    engine: str
    error_type: str
    error_message: str
    context: Dict[str, Any]
    resolved: bool = False
    resolution: str = ""
    resolved_at: str = ""

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class CorrectionEntry:
    id: str
    timestamp: str
    original_text: str
    corrected_text: str
    reason: str
    source: str  # "user" | "self_healer" | "llm"
    engine: str = ""

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class FixEntry:
    id: str
    timestamp: str
    engine: str
    error_pattern: str
    fix_description: str
    file_touched: str
    applied: bool
    auto: bool  # True = self-healed, False = user-confirmed
    confidence: float

    def to_dict(self) -> dict:
        return asdict(self)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _new_id(prefix: str) -> str:
    ts = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
    return f"{prefix}-{ts}-{uuid.uuid4().hex[:4]}"


def _append_jsonl(path: Path, entry: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")


def _read_jsonl(path: Path) -> List[dict]:
    if not path.exists():
        return []
    entries = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                try:
                    entries.append(json.loads(line))
                except json.JSONDecodeError:
                    pass
    return entries


def log_error(
    engine: str,
    error_type: str,
    error_message: str,
    context: Optional[Dict[str, Any]] = None,
) -> ErrorEntry:
    """Log an engine failure to the errors.jsonl vault log."""
    _ensure_dirs()
    entry = ErrorEntry(
        id=_new_id("ERR"),
        timestamp=_now_iso(),
        engine=engine,
        error_type=error_type,
        error_message=error_message,
        context=context or {},
    )
    _append_jsonl(LEARNINGS_DIR / "errors.jsonl", entry.to_dict())
    logger.info("[VAULT] Error logged: %s/%s — %s", engine, error_type, error_message[:80])
    return entry


def resolve_error(error_id: str, resolution: str) -> None:
    """Mark an error as resolved with the resolution text."""
    path = LEARNINGS_DIR / "errors.jsonl"
    entries = _read_jsonl(path)
    for e in entries:
        if e["id"] == error_id:
            e["resolved"] = True
            e["resolution"] = resolution
            e["resolved_at"] = _now_iso()
    # Rewrite entire file (jsonl is append-only for ingestion; updating is fine)
    with open(path, "w", encoding="utf-8") as f:
        for e in entries:
            f.write(json.dumps(e, ensure_ascii=False) + "\n")


def log_correction(
    original_text: str,
    corrected_text: str,
    reason: str,
    source: str = "user",
    engine: str = "",
) -> CorrectionEntry:
    """Log a user correction so Lazi learns not to make the same mistake."""
    _ensure_dirs()
    entry = CorrectionEntry(
        id=_new_id("COR"),
        timestamp=_now_iso(),
        original_text=original_text,
        corrected_text=corrected_text,
        reason=reason,
        source=source,
        engine=engine,
    )
    _append_jsonl(LEARNINGS_DIR / "corrections.jsonl", entry.to_dict())
    logger.info("[VAULT] Correction logged: %s", reason[:80])
    return entry


def log_fix(
    engine: str,
    error_pattern: str,
    fix_description: str,
    file_touched: str = "",
    applied: bool = True,
    auto: bool = True,
    confidence: float = 1.0,
) -> FixEntry:
    """Log a fix that was applied so future errors can be self-healed."""
    _ensure_dirs()
    entry = FixEntry(
        id=_new_id("FIX"),
        timestamp=_now_iso(),
        engine=engine,
        error_pattern=error_pattern,
        fix_description=fix_description,
        file_touched=file_touched,
        applied=applied,
        auto=auto,
        confidence=confidence,
    )
    _append_jsonl(LEARNINGS_DIR / "fixes_applied.jsonl", entry.to_dict())
    logger.info("[VAULT] Fix logged: %s — %s", engine, fix_description[:80])
    return entry


def get_recent_errors(engine: Optional[str] = None, limit: int = 20) -> List[ErrorEntry]:
    """Get recent errors, optionally filtered by engine."""
    path = LEARNINGS_DIR / "errors.jsonl"
    entries = _read_jsonl(path)
    if engine:
        entries = [e for e in entries if e.get("engine") == engine]
    entries = sorted(entries, key=lambda x: x.get("timestamp", ""), reverse=True)
    return [ErrorEntry(**e) for e in entries[:limit]]


def get_unresolved_errors() -> List[ErrorEntry]:
    """Get all unresolved errors for self-healing review."""
    path = LEARNINGS_DIR / "errors.jsonl"
    entries = _read_jsonl(path)
    return [ErrorEntry(**e) for e in entries if not e.get("resolved", False)]


def get_known_fixes(error_pattern: str) -> List[FixEntry]:
    """Find known fixes for an error pattern (substring match)."""
    path = LEARNINGS_DIR / "fixes_applied.jsonl"
    entries = _read_jsonl(path)
    return [FixEntry(**e) for e in entries
            if e.get("applied") and error_pattern.lower() in e.get("error_pattern", "").lower()]


def get_corrections(limit: int = 50) -> List[CorrectionEntry]:
    """Get recent corrections for Lazi to learn from."""
    path = LEARNINGS_DIR / "corrections.jsonl"
    entries = _read_jsonl(path)
    entries = sorted(entries, key=lambda x: x.get("timestamp", ""), reverse=True)
    return [CorrectionEntry(**e) for e in entries[:limit]]


# === Persona config (vault IS the source of truth at runtime) ===

def get_persona_config(persona: str) -> Dict[str, Any]:
    """Load persona config from vault/personas/. Falls back to personas/ dir."""
    vault_path = VAULT_DIR / "personas" / persona / "config.json"
    fallback_path = BASE_DIR / "personas" / persona / "search_config.yaml"
    if vault_path.exists():
        return json.loads(vault_path.read_text(encoding="utf-8"))
    if fallback_path.exists():
        import yaml
        return yaml.safe_load(fallback_path.read_text(encoding="utf-8")) or {}
    return {}


def save_persona_config(persona: str, config: Dict[str, Any]) -> None:
    """Save persona config to vault/personas/ (runtime source of truth)."""
    _ensure_dirs()
    vault_path = VAULT_DIR / "personas" / persona
    vault_path.mkdir(parents=True, exist_ok=True)
    (vault_path / "config.json").write_text(
        json.dumps(config, indent=2, ensure_ascii=False),
        encoding="utf-8"
    )


# === Job cache ===

def cache_job(persona: str, job: Dict[str, Any]) -> None:
    """Append a discovered job to the vault job cache."""
    _ensure_dirs()
    path = JOBS_DIR / persona
    path.mkdir(parents=True, exist_ok=True)
    job_entry = {**job, "cached_at": _now_iso(), "id": job.get("id") or _new_id("JOB")}
    _append_jsonl(path / "jobs.jsonl", job_entry)


def get_cached_jobs(persona: str, query: str = "", location: str = "") -> List[Dict[str, Any]]:
    """Get cached jobs for a persona, optionally filtered by query/location."""
    path = JOBS_DIR / persona / "jobs.jsonl"
    if not path.exists():
        return []
    jobs = _read_jsonl(path)
    if query:
        q = query.lower()
        jobs = [j for j in jobs
                if q in j.get("title", "").lower()
                or q in j.get("company", "").lower()
                or q in j.get("description", "").lower()]
    if location:
        loc = location.lower()
        jobs = [j for j in jobs if loc in j.get("location", "").lower()]
    return jobs


# === Vault singleton ===

class Vault:
    """
    Unified vault API. Import this to access everything.
    Usage:
        from app.vault import vault
        vault.store_credential("supply-chain-exec", "linkedin_session", cookies_str)
        vault.log_error("easyapplyjobsbot", "auth", "Session expired", {"url": "..."})
    """

    store_credential = staticmethod(store_credential)
    get_credential = staticmethod(get_credential)
    list_credentials = staticmethod(list_credentials)
    delete_credential = staticmethod(delete_credential)
    log_error = staticmethod(log_error)
    resolve_error = staticmethod(resolve_error)
    log_correction = staticmethod(log_correction)
    log_fix = staticmethod(log_fix)
    get_recent_errors = staticmethod(get_recent_errors)
    get_unresolved_errors = staticmethod(get_unresolved_errors)
    get_known_fixes = staticmethod(get_known_fixes)
    get_corrections = staticmethod(get_corrections)
    get_persona_config = staticmethod(get_persona_config)
    save_persona_config = staticmethod(save_persona_config)
    cache_job = staticmethod(cache_job)
    get_cached_jobs = staticmethod(get_cached_jobs)


# Convenience singleton
vault = Vault()
