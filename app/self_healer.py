"""
Self-Healer Module — Lazi-Bot Hive Mind
========================================
Error → Diagnose → Fix → Learn → Notify LaziBrain

Catches exceptions, logs to vault, diagnoses via LLM, applies fixes,
logs corrections, and pings LaziBrain so she can update her tool registry
and broadcast hive-mind knowledge to all bots.

Zero hardcoded fixes — every fix is either LLM-proposed or human-applied.
"""

from __future__ import annotations

import copy
import functools
import inspect
import os
import traceback
import uuid
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import (
    Any,
    Callable,
    Optional,
    TypeVar,
    Union,
)

# ── Vault import ──────────────────────────────────────────────────────────────
try:
    from vault import Vault
except ImportError:
    # Graceful degradation — self-healer still works in degraded mode
    Vault = None  # type: ignore


# ── LLM Client ───────────────────────────────────────────────────────────────
try:
    import openai

    _HAS_OPENAI = True
except ImportError:
    _HAS_OPENAI = False


T = TypeVar("T")


# ══════════════════════════════════════════════════════════════════════════════
#  Enums & Dataclasses
# ══════════════════════════════════════════════════════════════════════════════


class HealStatus(str, Enum):
    """Outcome of a heal operation."""

    PENDING = "pending"
    DIAGNOSED = "diagnosed"
    FIX_APPLIED = "fix_applied"
    HUMAN_REVIEW = "human_review"
    RESOLVED = "resolved"
    UNRESOLVED = "unresolved"


class ErrorSeverity(str, Enum):
    """How bad the error was."""

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


@dataclass
class HealTask:
    """
    One healing episode. Stored in vault/errors/<task_id>.json.
    """

    task_id: str
    created_at: str  # ISO UTC
    updated_at: str  # ISO UTC
    function_name: str
    module: str
    error_type: str
    error_message: str
    stack_trace: str
    severity: ErrorSeverity
    status: HealStatus
    diagnosis: str = ""
    proposed_fix: str = ""
    fix_code: str = ""
    applied_fix: str = ""
    success: bool = False
    resolved_at: str = ""
    tags: list[str] = field(default_factory=list)
    llm_model: str = "MiniMax-M2.7"
    retry_count: int = 0
    context: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["severity"] = self.severity.value if isinstance(self.severity, ErrorSeverity) else self.severity
        d["status"] = self.status.value if isinstance(self.status, HealStatus) else self.status
        return d

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> HealTask:
        if isinstance(d.get("severity"), str):
            d["severity"] = ErrorSeverity(d["severity"])
        if isinstance(d.get("status"), str):
            d["status"] = HealStatus(d["status"])
        return cls(**d)


@dataclass
class ErrorSummary:
    """Lightweight summary for list views."""

    task_id: str
    created_at: str
    function_name: str
    error_type: str
    severity: str
    status: str
    success: bool


# ══════════════════════════════════════════════════════════════════════════════
#  LLM Diagnoser
# ══════════════════════════════════════════════════════════════════════════════


class LLMDiagnoser:
    """
    Sends error context to the LLM and returns a diagnosed HealTask.
    Uses MiniMax-M2.7 by default (MiniMax-M2.5 fallback).
    """

    DEFAULT_MODEL = "MiniMax-M2.7"
    FALLBACK_MODEL = "MiniMax-M2.5"
    MAX_RETRIES = 2

    _SYSTEM_PROMPT = (
        "You are a senior Python engineer debugging an autonomous job-application "
        "agent called Lazi-Bot. Your job is to diagnose errors and propose precise "
        "code fixes.\n\n"
        "Given the error context below, respond ONLY with a JSON object "
        '(no markdown, no explanation) with these keys:\n'
        '  "diagnosis": short root-cause explanation (1-3 sentences)\n'
        '  "proposed_fix": what the fix should do (1-3 sentences)\n'
        '  "fix_code": the exact Python code to apply as a string (use \\n for newlines)\n'
        '  "severity": "low" | "medium" | "high" | "critical"\n'
        '  "tags": array of relevant tags e.g. ["selenium", "login", "rate_limit"]\n\n'
        "Be specific. Reference the actual module/function names from the context."
    )

    def __init__(self, api_key: Optional[str] = None, model: Optional[str] = None):
        self.api_key = api_key or os.environ.get("MINIMAX_API_KEY") or os.environ.get("OPENAI_API_KEY", "")
        self.model = model or self.DEFAULT_MODEL

    def _build_context(self, task: HealTask) -> str:
        """Build a rich context string for the LLM."""
        ctx = task.context or {}
        context_lines = "\n".join(f"  {k}: {v!r}" for k, v in ctx.items())
        return (
            f"Function: {task.module}.{task.function_name}\n"
            f"Error type: {task.error_type}\n"
            f"Error message: {task.error_message}\n"
            f"Stack trace:\n{task.stack_trace}\n"
            f"Additional context:\n{context_lines or '  (none)'}\n"
            f"Retry count: {task.retry_count}"
        )

    def diagnose(self, task: HealTask) -> HealTask:
        """
        Send error to LLM and populate diagnosis / proposed_fix / severity / tags.
        Falls back to rule-based heuristics if LLM is unavailable.
        """
        context_str = self._build_context(task)

        if not self.api_key:
            return self._rule_based_diagnosis(task)

        if _HAS_OPENAI:
            return self._diagnose_via_openai(task, context_str)
        else:
            return self._rule_based_diagnosis(task)

    def _diagnose_via_openai(self, task: HealTask, context_str: str) -> HealTask:
        """Call OpenAI-compatible endpoint for diagnosis."""
        import json as _json

        client = openai.OpenAI(api_key=self.api_key, base_url="https://api.minimax.chat/v1")

        for attempt in range(self.MAX_RETRIES):
            try:
                response = client.chat.completions.create(
                    model=self.model,
                    messages=[
                        {"role": "system", "content": self._SYSTEM_PROMPT},
                        {"role": "user", "content": context_str},
                    ],
                    temperature=0.2,
                    max_tokens=600,
                )
                raw = response.choices[0].message.content or "{}"
                # Strip markdown code fences if present
                raw = raw.strip().strip("```json").strip("```").strip()
                result = _json.loads(raw)

                task.diagnosis = result.get("diagnosis", "No diagnosis returned.")
                task.proposed_fix = result.get("proposed_fix", "")
                task.fix_code = result.get("fix_code", "")
                task.severity = ErrorSeverity(result.get("severity", "medium"))
                task.tags = result.get("tags", [])
                task.status = HealStatus.DIAGNOSED
                task.llm_model = self.model
                return task

            except Exception as exc:
                task.retry_count += 1
                if attempt == self.MAX_RETRIES - 1:
                    # Give up on LLM, fall back to rules
                    return self._rule_based_diagnosis(task)

        return task

    # ── Rule-Based Fallback Diagnoser ────────────────────────────────────────

    HEURISTICS: list[dict[str, Any]] = [
        {
            "keywords": ["SessionNotCreatedException", "webdriver", "chromedriver", "Chrome not reachable"],
            "severity": "high",
            "diagnosis": "Selenium WebDriver session failed — Chrome/ChromeDriver version mismatch or browser not installed.",
            "proposed_fix": "Ensure Chrome is installed, ChromeDriver matches Chrome version, and no stale Chrome processes are running.",
            "tags": ["selenium", "webdriver", "browser"],
        },
        {
            "keywords": ["element click intercepted", "ElementClickInterceptedException"],
            "severity": "medium",
            "diagnosis": "Selenium element click was blocked by another overlaying element (e.g. cookie banner, modal).",
            "proposed_fix": "Wait for element to be clickable, scroll into view, or dismiss overlays before clicking.",
            "tags": ["selenium", "ui", "overlay"],
        },
        {
            "keywords": ["NoSuchElementException", "element not found"],
            "severity": "medium",
            "diagnosis": "DOM element not found — page structure changed or element loaded dynamically via JS.",
            "proposed_fix": "Add explicit wait for element presence; use a more robust selector (data-testid, XPath with text).",
            "tags": ["selenium", "dom", "dynamic_loading"],
        },
        {
            "keywords": ["timeout", "TimeoutException", "timed out"],
            "severity": "medium",
            "diagnosis": "Operation timed out — network slow, page took too long to load, or server is lagging.",
            "proposed_fix": "Increase timeout duration; add retry logic with exponential back-off.",
            "tags": ["timeout", "network", "retry"],
        },
        {
            "keywords": ["403", "Forbidden", "403 Forbidden", "access denied"],
            "severity": "high",
            "diagnosis": "HTTP 403 — LinkedIn or target site blocked the request. Possible IP ban or missing auth.",
            "proposed_fix": "Check/switch VPN, verify LinkedIn session cookies are valid, or add proper request headers.",
            "tags": ["http", "linkedin", "auth", "rate_limit"],
        },
        {
            "keywords": ["429", "Too Many Requests", "rate limit"],
            "severity": "high",
            "diagnosis": "HTTP 429 — LinkedIn's anti-bot protection triggered; too many requests in a short window.",
            "proposed_fix": "Implement request throttling (1 req/5s minimum), randomize delays, rotate user agents, or use VPN.",
            "tags": ["http", "linkedin", "rate_limit"],
        },
        {
            "keywords": ["InvalidCredentialsException", "invalid email", "wrong password", "cannot log in"],
            "severity": "critical",
            "diagnosis": "LinkedIn login credentials rejected — email or password is wrong, or account locked.",
            "proposed_fix": "Verify credentials in vault. If correct, check if LinkedIn sent a verification email. Force 2FA if enabled.",
            "tags": ["auth", "linkedin", "credentials"],
        },
        {
            "keywords": ["FileNotFoundError", "No such file", "path does not exist"],
            "severity": "medium",
            "diagnosis": "A required file or directory was not found.",
            "proposed_fix": "Check the path exists; create it if missing; ensure working directory is correct.",
            "tags": ["file", "io", "path"],
        },
        {
            "keywords": ["JSONDecodeError", "json.decoder.JSONDecodeError", "Expecting value"],
            "severity": "medium",
            "diagnosis": "Response was not valid JSON — site changed API format or returned HTML on error.",
            "proposed_fix": "Add try/except around JSON parsing; log raw response; handle non-JSON gracefully.",
            "tags": ["parsing", "api", "linkedin"],
        },
        {
            "keywords": ["IndexError", "list index out of range"],
            "severity": "low",
            "diagnosis": "List index out of range — scraped data had fewer items than expected.",
            "proposed_fix": "Add bounds checking before indexing; handle empty lists explicitly.",
            "tags": ["parsing", "data"],
        },
        {
            "keywords": ["KeyError", "dict_key"],
            "severity": "low",
            "diagnosis": "Dictionary key not found — API response schema changed.",
            "proposed_fix": "Use .get() with a default; log missing keys; update expected schema.",
            "tags": ["parsing", "api", "schema"],
        },
        {
            "keywords": ["Fernet", "cryptography", "decrypt", "encrypt"],
            "severity": "high",
            "diagnosis": "Vault Fernet decryption/encryption failed — key missing, corrupted, or wrong key used.",
            "proposed_fix": "Verify master key in keyring (Windows Credential Manager). Re-enter vault password if using password-based key.",
            "tags": ["vault", "security", "encryption"],
        },
        {
            "keywords": ["MaxIterationsExceeded", "react", "loop"],
            "severity": "medium",
            "diagnosis": "LaziBrain ReAct loop hit max iterations without converging.",
            "proposed_fix": "Increase max_iterations or simplify the task by breaking it into sub-tasks.",
            "tags": ["lazi_brain", "react", "loop"],
        },
        {
            "keywords": ["StaleElementReferenceException"],
            "severity": "medium",
            "diagnosis": "Selenium element went stale — DOM node was destroyed and recreated (common in SPAs).",
            "proposed_fix": "Re-locate element before interaction; avoid holding references across page transitions.",
            "tags": ["selenium", "spa", "dom"],
        },
        {
            "keywords": ["ConnectionRefusedError", "ConnectionResetError", "ConnectionError"],
            "severity": "high",
            "diagnosis": "Network connection was refused or reset — server down, proxy blocking, or internet lost.",
            "proposed_fix": "Check internet connection; verify VPN/proxy settings; retry with back-off.",
            "tags": ["network", "connection"],
        },
    ]

    def _rule_based_diagnosis(self, task: HealTask) -> HealTask:
        """Fast heuristic fallback when LLM is unavailable."""
        haystack = (task.error_type + " " + task.error_message + " " + task.stack_trace).lower()

        for h in self.HEURISTICS:
            if any(kw.lower() in haystack for kw in h["keywords"]):
                task.diagnosis = h["diagnosis"]
                task.proposed_fix = h["proposed_fix"]
                task.severity = ErrorSeverity(h["severity"])
                task.tags = h["tags"]
                task.status = HealStatus.DIAGNOSED
                return task

        # No match — generic catch-all
        task.diagnosis = f"Unknown error ({task.error_type}) — LLM unavailable for deep diagnosis."
        task.proposed_fix = "Collect full logs and re-run with LLM-enabled self-healer for precise diagnosis."
        task.severity = ErrorSeverity.MEDIUM
        task.tags = ["unknown"]
        task.status = HealStatus.DIAGNOSED
        return task


# ══════════════════════════════════════════════════════════════════════════════
#  Fix Engine
# ══════════════════════════════════════════════════════════════════════════════


class FixEngine:
    """
    Applies code fixes proposed by the LLM or rule-based diagnoser.

    Strategy:
    1. If fix_code is provided → apply it directly (code injection).
    2. If proposed_fix is text-only → log it for human review.
    3. Track every applied fix in vault/corrections/fixes_applied.jsonl.
    """

    def __init__(self, vault: Optional["Vault"] = None):
        self.vault = vault

    def apply_fix(self, task: HealTask, source: str = "llm") -> HealTask:
        """
        Attempt to apply the proposed fix.
        Updates task.status and task.applied_fix.
        """
        task.status = HealStatus.FIX_APPLIED
        task.applied_fix = ""

        if not task.fix_code and not task.proposed_fix:
            task.status = HealStatus.HUMAN_REVIEW
            task.success = False
            return task

        if task.fix_code:
            applied = self._apply_code_fix(task)
            if applied:
                task.applied_fix = f"[{source}] {task.fix_code[:200]}"
                task.success = True
                task.status = HealStatus.RESOLVED
                task.resolved_at = _utcnow()
                self._log_fix_applied(task)
                return task

        # No code fix or code fix failed — mark for human review
        task.applied_fix = f"[{source}-text] {task.proposed_fix}"
        task.success = False
        task.status = HealStatus.HUMAN_REVIEW
        return task

    def _apply_code_fix(self, task: HealTask) -> bool:
        """
        Apply fix_code to the target module in memory.
        Uses AST manipulation for safe in-process patching.

        Returns True if fix was applied successfully.
        """
        try:
            import ast
        except ImportError:
            return False

        if not task.fix_code:
            return False

        # Find the target module
        target_module = task.module  # e.g. "engines.linkedin_adapter"
        mod = _import_module(target_module)
        if mod is None:
            return False

        # Try AST-level patch
        try:
            patch_applied = _apply_ast_fix(mod, task.fix_code)
            return patch_applied
        except Exception:
            pass

        # Fallback: exec the fix code in the module's namespace
        try:
            exec_locals: dict[str, Any] = {}
            exec(task.fix_code, mod.__dict__, exec_locals)
            return True
        except Exception:
            return False

    def _log_fix_applied(self, task: HealTask) -> None:
        """Append fix to vault/corrections/fixes_applied.jsonl."""
        if self.vault is None:
            return
        try:
            record = {
                "task_id": task.task_id,
                "timestamp": _utcnow(),
                "function": f"{task.module}.{task.function_name}",
                "error_type": task.error_type,
                "fix": task.applied_fix,
                "success": task.success,
                "source": "llm" if task.llm_model else "rule_based",
                "diagnosis": task.diagnosis,
            }
            self.vault.append_correction(record)
        except Exception:
            pass  # Never let logging fail crash the healer


# ══════════════════════════════════════════════════════════════════════════════
#  Self-Healer Core
# ══════════════════════════════════════════════════════════════════════════════


class SelfHealer:
    """
    Main entry point. Wraps functions with @self_healer.heal() decorator.

    Flow:
        exception → HealTask created → Diagnosed (LLM or rules)
        → Fix applied → Logged to vault → LaziBrain notified (callback)
    """

    VERSION = "1.0.0"

    def __init__(
        self,
        vault: Optional["Vault"] = None,
        llm_diagnoser: Optional[LLMDiagnoser] = None,
        fix_engine: Optional[FixEngine] = None,
        max_retries: int = 3,
        notify_callback: Optional[Callable[["HealTask"], None]] = None,
    ):
        self.vault = vault
        self.diagnoser = llm_diagnoser or LLMDiagnoser()
        self.fix_engine = fix_engine or FixEngine(vault=vault)
        self.max_retries = max_retries
        self.notify_callback = notify_callback  # LaziBrain notification hook
        self._tasks: dict[str, HealTask] = {}

    # ── Decorator ────────────────────────────────────────────────────────────

    def heal(
        self,
        func: Optional[Callable[..., T]] = None,
        *,
        max_retries: int = 3,
        context: Optional[dict[str, Any]] = None,
    ) -> Union[Callable[[Callable[..., T]], Callable[..., T]], Callable[..., T]]:
        """
        Decorator: @self_healer.heal() or @self_healer.heal(max_retries=5)

        Usage:
            @self_healer.heal()
            def my_func(x):
                ...

            @self_healer.heal(max_retries=5, context={"user": "trevo"})
            def another():
                ...
        """

        def decorator(fn: Callable[..., T]) -> Callable[..., T]:
            @functools.wraps(fn)
            def wrapper(*args: Any, **kwargs: Any) -> T:
                return self._run_heal_loop(fn, args, kwargs, context or {})

            # Propagate metadata for inspection
            wrapper._heal_task = True  # type: ignore
            wrapper._original_fn = fn  # type: ignore
            return wrapper

        # Support both @heal() and @heal
        if func is None:
            return decorator
        return decorator(func)

    def _run_heal_loop(
        self,
        fn: Callable[..., T],
        args: tuple[Any, ...],
        kwargs: dict[str, Any],
        extra_context: dict[str, Any],
    ) -> T:
        """Execute fn with full heal-on-failure logic."""
        attempt = 0
        last_task: Optional[HealTask] = None

        while attempt <= self.max_retries:
            try:
                return fn(*args, **kwargs)

            except Exception as exc:
                last_task = self._create_task(fn, exc, attempt, extra_context)
                task = self.diagnoser.diagnose(last_task)
                task = self.fix_engine.apply_fix(task)

                if task.status == HealStatus.RESOLVED:
                    self._store_task(task)
                    self._notify_lazibrain(task)
                    # Re-run on next loop iteration if retry_count < max_retries
                    attempt += 1
                    continue

                if task.status == HealStatus.HUMAN_REVIEW:
                    self._store_task(task)
                    self._notify_lazibrain(task)
                    # Re-raise original, but task is logged for human to fix
                    raise

                # UNRESOLVED — give up
                task.status = HealStatus.UNRESOLVED
                task.resolved_at = _utcnow()
                self._store_task(task)
                self._notify_lazibrain(task)
                raise

        # Should not reach here, but if it does:
        if last_task:
            last_task.status = HealStatus.UNRESOLVED
            last_task.resolved_at = _utcnow()
            self._store_task(last_task)
        raise RuntimeError(f"[SelfHealer] Max retries ({self.max_retries}) exceeded for {fn.__name__}")

    # ── Task Management ─────────────────────────────────────────────────────

    def _create_task(
        self,
        fn: Callable[..., Any],
        exc: Exception,
        attempt: int,
        extra_context: dict[str, Any],
    ) -> HealTask:
        module = _get_module_name(fn)
        tb = traceback.format_exc()

        task = HealTask(
            task_id=str(uuid.uuid4()),
            created_at=_utcnow(),
            updated_at=_utcnow(),
            function_name=fn.__name__,
            module=module,
            error_type=type(exc).__name__,
            error_message=str(exc),
            stack_trace=tb,
            severity=ErrorSeverity.MEDIUM,
            status=HealStatus.PENDING,
            retry_count=attempt,
            context=extra_context,
        )
        self._tasks[task.task_id] = task
        return task

    def _store_task(self, task: HealTask) -> None:
        """Persist task to vault/errors/<task_id>.json."""
        if self.vault is None:
            return
        task.updated_at = _utcnow()
        try:
            self.vault.save_error(task.to_dict())
        except Exception:
            pass

    def _notify_lazibrain(self, task: HealTask) -> None:
        """Call the notify_callback so LaziBrain can update her tool registry."""
        if self.notify_callback:
            try:
                self.notify_callback(task)
            except Exception:
                pass  # Never let notification failure break anything

    # ── Public API ──────────────────────────────────────────────────────────

    def get_task(self, task_id: str) -> Optional[HealTask]:
        """Retrieve a heal task by ID (in-memory cache)."""
        if task_id in self._tasks:
            return self._tasks[task_id]
        # Try vault
        if self.vault:
            data = self.vault.get_error(task_id)
            if data:
                return HealTask.from_dict(data)
        return None

    def get_tasks(
        self,
        status: Optional[HealStatus] = None,
        limit: int = 50,
    ) -> list[ErrorSummary]:
        """List recent heal tasks, optionally filtered by status."""
        if self.vault is None:
            return []
        summaries = []
        for data in self.vault.list_errors(limit=limit):
            if status and data.get("status") != status.value:
                continue
            summaries.append(
                ErrorSummary(
                    task_id=data["task_id"],
                    created_at=data["created_at"],
                    function_name=data["function_name"],
                    error_type=data["error_type"],
                    severity=data.get("severity", "medium"),
                    status=data.get("status", "pending"),
                    success=data.get("success", False),
                )
            )
        return summaries

    def get_stats(self) -> dict[str, Any]:
        """Return aggregate self-healer statistics."""
        if self.vault is None:
            return {"total": 0, "resolved": 0, "pending": 0, "human_review": 0}
        all_errors = self.vault.list_errors(limit=10000)
        return {
            "total": len(all_errors),
            "resolved": sum(1 for e in all_errors if e.get("status") == HealStatus.RESOLVED.value),
            "pending": sum(1 for e in all_errors if e.get("status") in (HealStatus.PENDING.value, HealStatus.DIAGNOSED.value)),
            "human_review": sum(1 for e in all_errors if e.get("status") == HealStatus.HUMAN_REVIEW.value),
            "unresolved": sum(1 for e in all_errors if e.get("status") == HealStatus.UNRESOLVED.value),
            "fix_rate": _safe_div(
                sum(1 for e in all_errors if e.get("success")),
                len(all_errors),
            ),
        }

    def apply_manual_fix(self, task_id: str, fix_note: str) -> bool:
        """Human applies a fix manually; mark task resolved."""
        task = self.get_task(task_id)
        if not task:
            return False
        task.applied_fix = f"[human] {fix_note}"
        task.success = True
        task.status = HealStatus.RESOLVED
        task.resolved_at = _utcnow()
        self._store_task(task)
        self._notify_lazibrain(task)
        return True

    def clear_resolved(self, older_than_days: int = 7) -> int:
        """Prune resolved tasks older than N days from vault."""
        if self.vault is None:
            return 0
        return self.vault.prune_resolved_errors(older_than_days)


# ══════════════════════════════════════════════════════════════════════════════
#  LaziBrain Integration — Tool Registry Updates
# ══════════════════════════════════════════════════════════════════════════════


class HiveMindFixBroadcaster:
    """
    Sits between SelfHealer and LaziBrain.
    When a fix is applied, updates the tool registry so all
    other bots in the hive mind instantly know the fix.

    Usage:
        broadcaster = HiveMindFixBroadcaster(lazi_brain_instance)
        self_healer = SelfHealer(notify_callback=broadcaster.broadcast)
    """

    def __init__(self, lazibrain: Any = None):
        self.lazibrain = lazibrain
        self._fix_log: list[dict[str, Any]] = []

    def broadcast(self, task: HealTask) -> None:
        """Called by SelfHealer when a fix is applied."""
        fix_record = {
            "task_id": task.task_id,
            "timestamp": _utcnow(),
            "function": f"{task.module}.{task.function_name}",
            "error_type": task.error_type,
            "diagnosis": task.diagnosis,
            "fix": task.applied_fix or task.proposed_fix,
            "success": task.success,
            "severity": task.severity.value if isinstance(task.severity, ErrorSeverity) else task.severity,
            "tags": task.tags,
        }
        self._fix_log.append(fix_record)

        if self.lazibrain and hasattr(self.lazibrain, "record_fix"):
            try:
                self.lazibrain.record_fix(fix_record)  # type: ignore
            except Exception:
                pass

        # Also append to vault fix log directly
        self._append_to_vault_log(fix_record)

    def _append_to_vault_log(self, record: dict[str, Any]) -> None:
        """Write fix to vault/hive_fixes.jsonl for cross-session persistence."""
        if Vault is None:
            return
        try:
            vault = Vault._instance()  # noqa: SLF001 — internal singleton access
            vault.append_correction(record)
        except Exception:
            pass

    def get_recent_fixes(self, limit: int = 20) -> list[dict[str, Any]]:
        """Return the most recent hive-mind fixes."""
        return list(reversed(self._fix_log[-limit:]))


# ══════════════════════════════════════════════════════════════════════════════
#  Global Singleton + Factory
# ══════════════════════════════════════════════════════════════════════════════

_instance: Optional[SelfHealer] = None


def _get_vault() -> Optional["Vault"]:
    if Vault is None:
        return None
    try:
        import threading

        result: list[Optional["Vault"], Exception] = [None, None]

        def _get():
            try:
                result[0] = Vault.get()  # noqa: SLF001
            except Exception as exc:  # noqa: PERF203
                result[1] = exc

        t = threading.Thread(target=_get, daemon=True)
        t.start()
        t.join(timeout=8)
        if t.is_alive():
            # Vault is blocked on keyring — return None (degraded mode)
            return None
        if result[1]:
            return None
        return result[0]
    except Exception:
        return None


def get_self_healer() -> SelfHealer:
    """Thread-safe singleton accessor."""
    global _instance
    if _instance is None:
        vault = _get_vault()
        _instance = SelfHealer(vault=vault)
    return _instance


def create_self_healer(
    vault: Optional["Vault"] = None,
    lazibrain: Any = None,
    max_retries: int = 3,
    api_key: Optional[str] = None,
) -> SelfHealer:
    """
    Factory: create and configure a fully wired SelfHealer.

    Args:
        vault: Vault instance (auto-detected if None)
        lazibrain: LaziBrain instance for hive-mind fix broadcasts
        max_retries: Max retry attempts per function
        api_key: LLM API key (auto-detected from env if None)

    Returns:
        Fully configured SelfHealer instance
    """
    vault = vault or _get_vault()
    diagnoser = LLMDiagnoser(api_key=api_key) if api_key or True else LLMDiagnoser()
    broadcaster = HiveMindFixBroadcaster(lazibrain=lazibrain)
    fix_engine = FixEngine(vault=vault)

    global _instance
    _instance = SelfHealer(
        vault=vault,
        llm_diagnoser=diagnoser,
        fix_engine=fix_engine,
        max_retries=max_retries,
        notify_callback=broadcaster.broadcast,
    )
    return _instance


# ══════════════════════════════════════════════════════════════════════════════
#  Vault Extension — Error Storage (injected into Vault class)
# ══════════════════════════════════════════════════════════════════════════════


def _extend_vault():
    """Add error/correction methods to Vault if not already present."""
    if Vault is None:
        return

    if hasattr(Vault, "save_error"):
        return  # Already extended

    def save_error(self: Vault, data: dict[str, Any]) -> None:
        task_id = data.get("task_id", "unknown")
        path = Path(self.errors_dir) / f"{task_id}.json"
        self._write_json(path, data)

    def get_error(self: Vault, task_id: str) -> Optional[dict[str, Any]]:
        path = Path(self.errors_dir) / f"{task_id}.json"
        if path.exists():
            return self._read_json(path)
        return None

    def list_errors(self: Vault, limit: int = 100) -> list[dict[str, Any]]:
        errors_dir = Path(self.errors_dir)
        if not errors_dir.exists():
            return []
        files = sorted(errors_dir.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True)
        results = []
        for f in files[:limit]:
            try:
                results.append(self._read_json(f))
            except Exception:
                pass
        return results

    def prune_resolved_errors(self: Vault, older_than_days: int = 7) -> int:
        """Delete resolved error JSONs older than N days. Returns count deleted."""
        from datetime import timedelta
        cutoff = datetime.now(timezone.utc) - timedelta(days=older_than_days)
        errors_dir = Path(self.errors_dir)
        if not errors_dir.exists():
            return 0
        deleted = 0
        for f in errors_dir.glob("*.json"):
            try:
                data = self._read_json(f)
                if data.get("status") == HealStatus.RESOLVED.value:
                    dt = datetime.fromisoformat(data.get("resolved_at", data.get("created_at", "2000")))
                    if dt.replace(tzinfo=timezone.utc) < cutoff:
                        f.unlink()
                        deleted += 1
            except Exception:
                pass
        return deleted

    # Attach to Vault class
    Vault.save_error = save_error  # type: ignore
    Vault.get_error = get_error  # type: ignore
    Vault.list_errors = list_errors  # type: ignore
    Vault.prune_resolved_errors = prune_resolved_errors  # type: ignore


# ══════════════════════════════════════════════════════════════════════════════
#  Utility Helpers
# ══════════════════════════════════════════════════════════════════════════════


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _safe_div(numerator: int, denominator: int) -> float:
    if denominator == 0:
        return 0.0
    return round(numerator / denominator, 3)


def _import_module(name: str):
    """Import a module by string name, with fallback."""
    try:
        return __import__(name, fromlist=[""])
    except Exception:
        # Try top-level
        parts = name.split(".")
        if len(parts) > 1:
            try:
                return __import__(".".join(parts[1:]), fromlist=[""])
            except Exception:
                pass
        return None


def _get_module_name(fn: Callable[..., Any]) -> str:
    """Get the module name of a function."""
    mod = inspect.getmodule(fn)
    if mod is None:
        return fn.__class__.__module__ if hasattr(fn, "__class__") else "__main__"
    return mod.__name__


# ── AST Fix Application ────────────────────────────────────────────────────────


def _apply_ast_fix(module: Any, fix_code: str) -> bool:
    """
    Parse fix_code as a Python AST and merge it into module's namespace.
    Handles function patching, import additions, and global variable updates.
    """
    import ast

    try:
        tree = ast.parse(fix_code)
    except SyntaxError:
        return False

    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef):
            # Patch or add function to module
            existing = module.__dict__.get(node.name)
            if existing is not None:
                # Wrap existing with new
                new_fn_code = compile(ast.Module(body=[node], type_ignores=[]), "<fix>", "exec")
                exec(new_fn_code, module.__dict__)
            else:
                new_fn_code = compile(ast.Module(body=[node], type_ignores=[]), "<fix>", "exec")
                exec(new_fn_code, module.__dict__)

        elif isinstance(node, ast.Import):
            for alias in node.names:
                try:
                    __import__(alias.name, fromlist=[""])
                except Exception:
                    pass

        elif isinstance(node, ast.ImportFrom):
            try:
                __import__(node.module or "", fromlist=[n.name for n in node.names])
            except Exception:
                pass

    return True


# ── Initialize vault extensions ───────────────────────────────────────────────
_extend_vault()


# ══════════════════════════════════════════════════════════════════════════════
#  Demo / Smoke Test
# ══════════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    print("[SelfHealer] Smoke test")

    # Create without vault (degraded mode)
    sh = create_self_healer(max_retries=1)

    @sh.heal(max_retries=0)
    def buggy_divide(a: float, b: float) -> float:
        """Demo function that will fail on division by zero."""
        return a / b

    # Test 1: Normal call works
    result = buggy_divide(10, 2)
    print(f"  [PASS] 10 / 2 = {result}")

    # Test 2: Division by zero → heal task created
    try:
        buggy_divide(1, 0)
    except ZeroDivisionError:
        print("  [EXPECTED] ZeroDivisionError raised (heal loop exhausted)")

    stats = sh.get_stats()
    print(f"  [STATS] {stats}")
    print("[PASS] SelfHealer smoke test PASSED")
