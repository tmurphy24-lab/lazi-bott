"""
Encrypted password vault for linkedin-autopilot.

Stores usernames, passwords, URLs, and notes for any site (LinkedIn, GitHub,
Indeed, Gmail, etc.). The vault file itself is encrypted with Fernet, and the
Fernet key is stored in the OS credential manager (keyring) so the vault is
unusable without the same OS user.

Vault path: linkedin-autopilot/keys/vault.enc
Master key:  stored in keyring under "linkedin-autopilot" / "vault_key"

Public API:
    store_entry(site, username, password, url="", notes="") -> Entry
    get_entry(site) -> Optional[Entry]
    list_sites() -> List[str]
    delete_entry(site) -> bool
    update_entry(site, **fields) -> Entry
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import List, Optional, Dict, Any

import keyring
from cryptography.fernet import Fernet, InvalidToken

from .profile_store import KEYS_DIR

logger = logging.getLogger(__name__)

VAULT_PATH = KEYS_DIR / "vault.enc"
KEYRING_KEY = "vault_key"   # stored under KEYRING_APP="linkedin-autopilot"


@dataclass
class Entry:
    site: str
    username: str
    password: str
    url: str = ""
    notes: str = ""

    def to_dict(self) -> dict:
        return asdict(self)


# --- master key management ---

def _get_or_create_master_key() -> bytes:
    """Get the Fernet key from keyring, or generate and store a new one."""
    from .profile_store import KEYRING_APP
    existing = keyring.get_password(KEYRING_APP, KEYRING_KEY)
    if existing:
        return existing.encode("utf-8")
    new_key = Fernet.generate_key()
    keyring.set_password(KEYRING_APP, KEYRING_KEY, new_key.decode("utf-8"))
    logger.info("Generated new master key, stored in OS credential manager")
    return new_key


def _fernet() -> Fernet:
    return Fernet(_get_or_create_master_key())


# --- vault I/O ---

def _read_vault() -> Dict[str, Dict[str, Any]]:
    if not VAULT_PATH.exists():
        return {}
    try:
        raw = VAULT_PATH.read_bytes()
        decrypted = _fernet().decrypt(raw)
        return json.loads(decrypted.decode("utf-8"))
    except (InvalidToken, json.JSONDecodeError, OSError) as e:
        logger.error("Vault read failed: %s. Vault may be corrupt.", e)
        return {}


def _write_vault(data: Dict[str, Dict[str, Any]]) -> None:
    KEYS_DIR.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(data, indent=2, ensure_ascii=False).encode("utf-8")
    encrypted = _fernet().encrypt(payload)
    VAULT_PATH.write_bytes(encrypted)
    logger.info("Vault written: %d entries", len(data))


# --- public API ---

def store_entry(site: str, username: str, password: str, url: str = "", notes: str = "") -> Entry:
    """Add or replace an entry."""
    data = _read_vault()
    data[site.lower()] = {
        "site": site, "username": username, "password": password,
        "url": url, "notes": notes,
    }
    _write_vault(data)
    return Entry(site, username, password, url, notes)


def get_entry(site: str) -> Optional[Entry]:
    """Look up a site. Site match is case-insensitive."""
    data = _read_vault()
    entry = data.get(site.lower())
    if not entry:
        return None
    return Entry(**entry)


def list_sites() -> List[str]:
    """Return the list of stored site names."""
    return sorted(_read_vault().keys())


def delete_entry(site: str) -> bool:
    """Remove an entry. Returns True if removed."""
    data = _read_vault()
    if site.lower() in data:
        del data[site.lower()]
        _write_vault(data)
        return True
    return False


def update_entry(site: str, **fields) -> Optional[Entry]:
    """Partial update; only provided fields are replaced."""
    data = _read_vault()
    entry = data.get(site.lower())
    if not entry:
        return None
    for k, v in fields.items():
        if k in entry:
            entry[k] = v
    _write_vault(data)
    return Entry(**entry)
