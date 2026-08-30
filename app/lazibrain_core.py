"""
LaziBrain Core — Phase 2 Enhanced Supervisor Agent
=================================================
Replaces the simple LaziBrain in lazibot.py with the full:
  - Event bus: statuschange / historychange / activity
  - Tool registry: 6 engines + helper tools
  - Enhanced ReAct loop: observe → think → reflect → act → loop
  - MCP Bridge integration: page-agent as Engine 6
  - AbortSignal support for cancellable tool calls

All existing QObject signals (reply, command) are preserved for
backward compatibility with LaziChatOverlay and TheCouch.
"""

from __future__ import annotations

import asyncio
import logging
import random
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Callable, Dict, List, Optional

from PySide6.QtCore import QObject, Signal, QTimer

from app.ui_kit import LaziColors

from .tool_decorator import (
    Tool,
    get_tool,
    get_tool_registry,
    register_tool,
    AbortedError,
    ToolExecutionError,
)

logger = logging.getLogger(__name__)


# ══════════════════════════════════════════════════════════════════════════════
#  Event Types
# ══════════════════════════════════════════════════════════════════════════════


class AgentStatus(str, Enum):
    IDLE = "idle"
    RUNNING = "running"
    COMPLETED = "completed"
    ERROR = "error"
    STOPPED = "stopped"


@dataclass
class HistoryEvent:
    """One event in the agent's persistent history (fed to LLM context)."""
    type: str  # "step" | "observation" | "error" | "user_takeover"
    step: int = 0
    reflection: Optional[dict] = None
    action: Optional[dict] = None
    content: Optional[str] = None
    usage: Optional[dict] = None
    timestamp: str = ""


@dataclass
class AgentActivity:
    """Transient real-time activity for UI display — NOT in LLM context."""
    type: str  # "thinking" | "executing" | "executed" | "retrying" | "error"
    tool: Optional[str] = None
    input_data: Optional[dict] = None
    output: Any = None
    attempt: int = 0
    max_attempts: int = 1
    duration_ms: int = 0
    message: str = ""


# ══════════════════════════════════════════════════════════════════════════════
#  Execution Result
# ══════════════════════════════════════════════════════════════════════════════


@dataclass
class ExecutionResult:
    success: bool
    data: Any
    history: List[HistoryEvent] = field(default_factory=list)
    error: Optional[str] = None


# ══════════════════════════════════════════════════════════════════════════════
#  LaziBrain Core
# ══════════════════════════════════════════════════════════════════════════════


class LaziBrainCore(QObject):
    """
    Enhanced supervisor agent. Backward-compatible with the original LaziBrain
    (same reply signal, same configure() interface).

    New capabilities:
      - Event bus: statuschange / historychange / activity signals
      - Tool registry: @register_tool decorated functions
      - ReAct loop: enhanced with reflection steps + AbortSignal cancellation
      - MCP Bridge: page-agent as Engine 6
      - Cancellable tool execution
    """

    # ── Qt signals (backward-compatible) ──────────────────────────────────
    reply = Signal(str)  # existing: LaziChatOverlay listens for this

    # ── New event signals ──────────────────────────────────────────────────
    status_changed = Signal(str)  # AgentStatus value
    history_changed = Signal(dict)  # HistoryEvent as dict
    activity_changed = Signal(dict)  # AgentActivity as dict

    MAX_ITERATIONS = 10
    MAX_HISTORY = 20  # most recent N turns in LLM context

    def __init__(
        self,
        parent=None,
        mcp_bridge=None,
        vault=None,
    ):
        super().__init__(parent)
        # Existing config (backward-compatible)
        self.provider = "poolside"
        self.api_key = None

        # New: MCP Bridge (page-agent Engine 6)
        self.mcp_bridge = mcp_bridge

        # New: Vault for learnings
        self.vault = vault

        # New: Tool registry
        self._tools: Dict[str, Tool] = get_tool_registry()

        # New: ReAct state
        self._abort_controller: Optional[_AbortController] = None
        self._history: List[HistoryEvent] = []
        self._status = AgentStatus.IDLE

        # New: Hooks
        self._on_before_step: Optional[Callable] = None
        self._on_after_step: Optional[Callable] = None

        # LLM config
        self._llm_base_urls = {
            "poolside": "https://inference.poolside.ai/v1",
            "openai": "https://api.openai.com/v1",
            "minimax": "https://api.minimax.chat/v1",
        }

    # ── Configuration ────────────────────────────────────────────────────────

    def configure(self, provider: str, api_key: Optional[str]):
        """Backward-compatible with existing LaziBrain configure() calls."""
        self.provider = provider
        self.api_key = api_key

    def set_mcp_bridge(self, bridge):
        """Inject the MCP Bridge (page-agent connection)."""
        self.mcp_bridge = bridge

    def set_vault(self, vault):
        """Inject the Vault (learnings/logs)."""
        self.vault = vault

    def register_tool(self, name: str, func: Callable, description: str = "", input_schema: Optional[dict] = None):
        """Register a function as a LaziBrain tool."""
        tool = register_tool(
            name=name,
            description=description,
            input_schema=input_schema,
        )(func)

        # Also update local registry
        t = get_tool(name)
        if t:
            self._tools[name] = t
        return tool

    # ── Event helpers ────────────────────────────────────────────────────────

    def _set_status(self, status: AgentStatus):
        if self._status != status:
            self._status = status
            self.status_changed.emit(status.value)

    def _emit_activity(self, activity: AgentActivity):
        self.activity_changed.emit({
            "type": activity.type,
            "tool": activity.tool,
            "input_data": activity.input_data,
            "output": activity.output,
            "attempt": activity.attempt,
            "max_attempts": activity.max_attempts,
            "duration_ms": activity.duration_ms,
            "message": activity.message,
        })

    def _push_history(self, event: HistoryEvent):
        self._history.append(event)
        self.history_changed.emit({
            "type": event.type,
            "step": event.step,
            "content": event.content,
            "timestamp": event.timestamp,
        })

    # ── Main ReAct loop ─────────────────────────────────────────────────────

    async def ask_async(self, task: str, system_prompt: str = "") -> ExecutionResult:
        """
        Enhanced ReAct loop — async version that returns ExecutionResult.

        Loop per iteration:
          1. OBSERVE   → gather observations (page state, vault logs)
          2. THINK     → LLM generates MacroTool input
          3. REFLECT   → build reflection text
          4. ACT       → execute selected tool with AbortSignal
          5. LOOP      → max MAX_ITERATIONS, then summarize partial

        Can be called from Qt background thread.
        """
        self._set_status(AgentStatus.RUNNING)
        self._history = []
        self._abort_controller = _AbortController()

        task_id = str(uuid.uuid4())

        for step in range(self.MAX_ITERATIONS):
            # Check for abort
            self._abort_controller.raise_if_aborted()

            # ── 1. OBSERVE ────────────────────────────────────────────────
            observations = self._gather_observations(step)
            for obs in observations:
                self._push_history(HistoryEvent(
                    type="observation",
                    content=obs,
                    timestamp=datetime.now(timezone.utc).isoformat(),
                ))

            # ── 2. THINK — LLM generates MacroToolInput ─────────────────
            self._emit_activity(AgentActivity(type="thinking"))

            macro_input = await self._llm_macrotool(task, system_prompt)

            if macro_input is None:
                return ExecutionResult(
                    success=False,
                    error="LLM call failed",
                    history=self._history,
                )

            reflection = {
                "evaluation_previous_goal": macro_input.get("evaluation_previous_goal", ""),
                "memory": macro_input.get("memory", ""),
                "next_goal": macro_input.get("next_goal", ""),
            }

            action = macro_input.get("action", {})
            action_name = list(action.keys())[0] if action else "done"
            action_input = action.get(action_name, {}) if action else {}

            # ── 3. REFLECT — push to history ───────────────────────────────
            history_event = HistoryEvent(
                type="step",
                step=step,
                reflection=reflection,
                action={"name": action_name, "input": action_input},
                timestamp=datetime.now(timezone.utc).isoformat(),
            )
            self._push_history(history_event)

            # ── Check for done ────────────────────────────────────────────
            if action_name == "done":
                success = action_input.get("success", True)
                text = action_input.get("text", "Task completed")
                self._set_status(AgentStatus.COMPLETED)
                return ExecutionResult(success=success, data=text, history=self._history)

            # ── 4. ACT — execute tool with AbortSignal ──────────────────
            self._emit_activity(AgentActivity(
                type="executing",
                tool=action_name,
                input_data=action_input,
            ))

            import time
            start_ms = int(time.time() * 1000)
            try:
                tool_result = await self._execute_tool(action_name, action_input)
            except AbortedError as exc:
                self._set_status(AgentStatus.STOPPED)
                return ExecutionResult(success=False, error=str(exc), history=self._history)
            except Exception as exc:
                tool_result = f"[ERROR] {exc}"
                if self.vault:
                    self.vault.log_failure(action_name, str(exc), {"step": step, "task": task})

            duration_ms = int(time.time() * 1000) - start_ms
            self._emit_activity(AgentActivity(
                type="executed",
                tool=action_name,
                input_data=action_input,
                output=tool_result,
                duration_ms=duration_ms,
            ))

            # Push tool result as observation
            self._push_history(HistoryEvent(
                type="observation",
                content=f"[{action_name}] → {tool_result}",
                timestamp=datetime.now(timezone.utc).isoformat(),
            ))

            # Abort check after tool
            self._abort_controller.raise_if_aborted()

        # Max iterations reached
        summary = self._summarize_partial()
        self._set_status(AgentStatus.ERROR)
        return ExecutionResult(success=False, data=summary, history=self._history)

    def ask(self, user_msg: str, system_prompt: str = "") -> None:
        """
        Backward-compatible: Qt slot that calls ask_async and emits reply.
        Uses QTimer to keep GUI responsive.
        """
        self._history.append({"role": "user", "content": user_msg})

        def _run():
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            try:
                result = loop.run_until_complete(self.ask_async(user_msg, system_prompt))
                text = result.data if result.success else f"Stopped: {result.error}"
            except Exception as exc:
                text = f"Error: {exc}"
            finally:
                loop.close()

            self.reply.emit(text)

        QTimer.singleShot(0, _run)

    def stop(self):
        """Cancel the current ReAct loop."""
        if self._abort_controller:
            self._abort_controller.abort()

    # ── LLM call ────────────────────────────────────────────────────────────

    async def _llm_macrotool(self, task: str, system_prompt: str) -> Optional[dict]:
        """
        Call the LLM with the MacroTool format.
        Returns the parsed MacroToolInput dict, or None on failure.
        """
        try:
            import openai
        except ImportError:
            return self._llm_canned_macrotool(task)

        try:
            base = self._llm_base_urls.get(self.provider, self._llm_base_urls["openai"])
            client = openai.OpenAI(api_key=self.api_key or "no-key", base_url=base)

            messages = self._build_messages(task, system_prompt)
            system_msg = messages[0]["content"] if messages and messages[0]["role"] == "system" else ""
            user_msgs = [m for m in messages if m["role"] != "system"]
            user_content = "\n\n".join(
                f"[{m['role']}] {m['content']}" for m in user_msgs[-self.MAX_HISTORY:]
            )

            # Build a structured prompt with the tool schema
            tool_schemas = self._get_tool_schemas_for_llm()
            full_system = (
                f"{system_msg}\n\n"
                f"You have these tools available:\n{tool_schemas}\n\n"
                f"After each step, output a JSON block with your reasoning.\n"
                f"Format:\n"
                f"{{'evaluation_previous_goal': '...', 'memory': '...', "
                f"'next_goal': '...', 'action': {{'tool_name': {{...input...}}}}}}"
            )

            resp = client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[
                    {"role": "system", "content": full_system},
                    {"role": "user", "content": user_content},
                ],
                max_tokens=600,
                temperature=0.3,
            )
            raw = resp.choices[0].message.content or ""
            return self._parse_macrotool_response(raw)

        except Exception as exc:
            logger.warning("LLM call failed: %s", exc)
            return None

    def _llm_canned_macrotool(self, task: str) -> dict:
        """Fallback when no LLM is available — generates a reasonable canned response."""
        # Simple rule-based canned responses
        task_lower = task.lower()
        if "scrape" in task_lower or "linkedin" in task_lower:
            action = {
                "page_agent": {
                    "task": f"Navigate to LinkedIn and find jobs matching: {task}",
                    "wait_for": 3,
                }
            }
        elif "apply" in task_lower:
            action = {"easyapplyjobsbot": {"query": task, "location": "Remote", "max_jobs": 5}}
        else:
            action = {"done": {"success": True, "text": f"Understood: {task}"}}

        return {
            "evaluation_previous_goal": "",
            "memory": "",
            "next_goal": f"Handle request: {task}",
            "action": action,
        }

    # ── Tool execution ───────────────────────────────────────────────────────

    async def _execute_tool(self, name: str, input_data: dict) -> str:
        """
        Execute a tool by name. Supports:
          - Registered Python tools (via @tool decorator)
          - page_agent tool → MCP Bridge → page-agent in browser
          - done tool → handled specially in the loop
        """
        if name == "done":
            return "done"

        if name == "page_agent":
            # Engine 6: route to MCP Bridge → page-agent
            if self.mcp_bridge and self.mcp_bridge.is_connected:
                result = await self.mcp_bridge.call_tool(
                    "execute_task",
                    {
                        "task": input_data.get("task", ""),
                        "url": input_data.get("tab_url", ""),
                        "wait_for": input_data.get("wait_for", 2),
                    },
                )
                return result.text
            else:
                return "[page-agent not connected] Start the MCP bridge first."

        # Python tool (via tool registry)
        tool = get_tool(name)
        if not tool:
            return f"[ERROR] Unknown tool: {name}"

        signal = self._abort_controller._signal if self._abort_controller else None

        def _sync_execute():
            return tool.execute(input_data, {"signal": signal})

        # Run in thread pool to keep Qt reactive
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, _sync_execute)

    # ── Message building ──────────────────────────────────────────────────────

    def _build_messages(self, task: str, system_prompt: str) -> List[dict]:
        """Build the full message list for the LLM."""
        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        return messages

    def _get_tool_schemas_for_llm(self) -> str:
        """Format tool registry as a string for the LLM system prompt."""
        lines = []
        for name, tool in self._tools.items():
            lines.append(f"\nTool: {name}")
            lines.append(f"  Description: {tool.description}")
            if tool.input_schema:
                props = tool.input_schema.get("properties", {})
                if props:
                    lines.append(f"  Parameters:")
                    for pname, pdef in props.items():
                        ptype = pdef.get("type", "any")
                        required = pname in tool.input_schema.get("required", [])
                        req_mark = " (required)" if required else ""
                        lines.append(f"    - {pname}: {ptype}{req_mark}")
        return "\n".join(lines) or "(no tools registered)"

    # ── Observation gathering ─────────────────────────────────────────────────

    def _gather_observations(self, step: int) -> List[str]:
        """
        Gather observations before each ReAct step.
        These go into history as 'observation' events and into LLM context.
        """
        obs = []

        # Remaining steps warning
        remaining = self.MAX_ITERATIONS - step
        if remaining == 5:
            obs.append(f"⚠️ Only {remaining} steps remaining. Wrap up or call done.")
        elif remaining == 2:
            obs.append(f"⚠️ Critical: only {remaining} steps left! Finish or call done.")

        # From vault: recent errors
        if self.vault:
            try:
                recent_errors = self.vault.get_recent_errors(limit=3)
                if recent_errors:
                    obs.append(f"Recent errors: {recent_errors}")
            except Exception:
                pass

        return obs

    # ── Helpers ──────────────────────────────────────────────────────────────

    def _parse_macrotool_response(self, raw: str) -> Optional[dict]:
        """Extract MacroToolInput dict from LLM raw text response."""
        import json
        import re

        # Try to find a JSON block
        match = re.search(r"\{[^{}]*'evaluation_previous_goal'[^{}]*\}", raw, re.DOTALL)
        if not match:
            # Try simpler: look for {...}
            matches = re.findall(r"\{.*?\}", raw, re.DOTALL)
            for m in reversed(matches):  # last JSON blob is usually the answer
                try:
                    d = json.loads(m)
                    if "action" in d or "next_goal" in d:
                        return d
                except Exception:
                    pass
            return None

        try:
            return json.loads(match.group())
        except Exception:
            return None

    def _summarize_partial(self) -> str:
        """Summarize what the agent accomplished before running out of steps."""
        steps_done = len([e for e in self._history if e.type == "step"])
        return (
            f"Ran out of steps ({self.MAX_ITERATIONS}). "
            f"Completed {steps_done} step(s) before timeout. "
            f"Check history for details."
        )


# ══════════════════════════════════════════════════════════════════════════════
#  Abort Controller (signal-based cancellation)
# ══════════════════════════════════════════════════════════════════════════════


class _AbortController:
    """
    Lightweight AbortSignal equivalent.
    LaziBrain calls abort() to cancel the current ReAct loop.
    Tool calls call raise_if_aborted() at checkpoints.
    """

    def __init__(self):
        self._aborted = False

    def abort(self):
        self._aborted = True

    def raise_if_aborted(self):
        if self._aborted:
            raise AbortedError("Task aborted by LaziBrain")

    @property
    def signal(self):
        """Compatible with code that checks `if signal: signal.raise_if_aborted()`"""
        return self
