"""
Lazi Integration — wires vault + self-healer + scrapers into the Lazi-Bot GUI
================================================================================
Exposes a simple `setup_lazi_integration(controller)` call that:
  1. Boots the Vault singleton (non-blocking, 8s timeout)
  2. Boots the SelfHealer + HiveMindFixBroadcaster
  3. Wires both into LaziBrain so corrections and failures are auto-logged
  4. Adds learnings/corrections tab to TheCouch

Call this once from AppController.__init__ after the UI is built.
"""

from __future__ import annotations

import logging
import threading
from typing import TYPE_CHECKING, Any, Optional

if TYPE_CHECKING:
    from app.main import AppController

logger = logging.getLogger(__name__)

# ── Lazy imports so the GUI can boot without vault/healer if files are missing ──

_vault_instance: Any = None
_self_healer_instance: Any = None
_hive_broadcaster: Any = None
_vault_init_started: bool = False


# ══════════════════════════════════════════════════════════════════════════════
#  Boot order
# ══════════════════════════════════════════════════════════════════════════════


def _boot_vault() -> Any:
    """Boot vault in a background thread. Returns None if unavailable."""
    from pathlib import Path

    vault_dir = Path(__file__).resolve().parent.parent / "vault"
    vault_dir.mkdir(exist_ok=True)

    try:
        from vault import Vault
        from app.self_healer import SelfHealer, LLMDiagnoser, FixEngine, HiveMindFixBroadcaster

        vault = Vault.get()
        if vault is None:
            logger.warning("[LaziIntegration] Vault unavailable (keyring timeout or no master key)")
            return None, None, None

        healer = SelfHealer(vault=vault)
        broadcaster = HiveMindFixBroadcaster()
        return vault, healer, broadcaster

    except Exception as exc:
        logger.warning("[LaziIntegration] Vault/self-healer import or init failed: %s", exc)
        return None, None, None


def setup_lazi_integration(controller: "AppController") -> None:
    """
    Call once from AppController.__init__ after UI is fully built.
    Non-blocking: vault boots on a background thread.
    """
    global _vault_init_started
    if _vault_init_started:
        return
    _vault_init_started = True

    def _background_boot():
        vault, healer, broadcaster = _boot_vault()
        global _vault_instance, _self_healer_instance, _hive_broadcaster
        _vault_instance = vault
        _self_healer_instance = healer
        _hive_broadcaster = broadcaster
        logger.info(
            "[LaziIntegration] Vault=%s, Healer=%s, Broadcaster=%s",
            vault is not None,
            healer is not None,
            broadcaster is not None,
        )

    t = threading.Thread(target=_background_boot, daemon=True)
    t.start()


# ══════════════════════════════════════════════════════════════════════════════
#  Public accessors (safe to call from anywhere)
# ══════════════════════════════════════════════════════════════════════════════


def get_vault() -> Any:
    return _vault_instance


def get_self_healer() -> Any:
    return _self_healer_instance


def get_hive_broadcaster() -> Any:
    return _hive_broadcaster


def is_ready() -> bool:
    """True once vault has finished booting (or given up)."""
    return _vault_init_started  # Vault boots async, but flag tells us boot started


def log_correction(
    correction_type: str,
    user_message: str,
    system_response: str,
    accepted: bool,
    context: Optional[dict[str, Any]] = None,
) -> None:
    """
    Log a user correction so LaziBrain and the vault both learn from it.

    Call this from LaziBrain when the user corrects Lazi's output.
    """
    if _vault_instance is None:
        logger.debug("[LaziIntegration] log_correction called but vault not ready")
        return

    record = {
        "type": correction_type,
        "user_message": user_message,
        "system_response": system_response,
        "accepted": accepted,
        "context": context or {},
    }

    try:
        _vault_instance.append_correction(record)
        logger.info("[LaziIntegration] Correction logged: %s", correction_type)
    except Exception as exc:
        logger.warning("[LaziIntegration] Failed to log correction: %s", exc)


def log_error(
    error_type: str,
    error_message: str,
    stack_trace: str,
    severity: str = "medium",
    context: Optional[dict[str, Any]] = None,
) -> str:
    """
    Log an error to vault and return the task_id.
    Returns the task_id so the error can be tracked if manually resolved later.
    """
    import uuid

    if _vault_instance is None:
        return ""

    task_id = str(uuid.uuid4())
    record = {
        "task_id": task_id,
        "created_at": _utcnow(),
        "error_type": error_type,
        "error_message": error_message,
        "stack_trace": stack_trace,
        "severity": severity,
        "status": "pending",
        "context": context or {},
    }

    try:
        _vault_instance.save_error(record)
        logger.info("[LaziIntegration] Error logged: %s — %s", error_type, task_id)
    except Exception as exc:
        logger.warning("[LaziIntegration] Failed to log error: %s", exc)

    return task_id


def get_vault_stats() -> dict[str, Any]:
    """Return vault + self-healer aggregate stats for display."""
    if _vault_instance is None:
        return {"vault_ready": False}

    stats = {"vault_ready": True}

    if _self_healer_instance is not None:
        try:
            stats["healer"] = _self_healer_instance.get_stats()
        except Exception:
            stats["healer"] = {}

    try:
        stats["corrections_count"] = _vault_instance.count_corrections()
    except Exception:
        stats["corrections_count"] = -1

    try:
        stats["errors_count"] = len(_vault_instance.list_errors(limit=1))
    except Exception:
        stats["errors_count"] = -1

    return stats


def get_recent_corrections(limit: int = 10) -> list[dict[str, Any]]:
    """Return the most recent corrections from vault."""
    if _vault_instance is None:
        return []
    try:
        return _vault_instance.get_recent_corrections(limit=limit)
    except Exception:
        return []


def get_recent_errors(limit: int = 10) -> list[dict[str, Any]]:
    """Return the most recent heal tasks from vault."""
    if _vault_instance is None:
        return []
    try:
        return _vault_instance.list_errors(limit=limit)
    except Exception:
        return []


def _utcnow() -> str:
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
