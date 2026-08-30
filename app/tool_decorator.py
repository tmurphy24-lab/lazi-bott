"""
@tool Decorator + Tool Registry — Lazi-Bot Phase 2
=====================================================
Cancellable tool execution with AbortSignal support.
Every tool in LaziBrain's registry is a decorated function.

Usage:
    @tool(name="scrape_linkedin", description="Scrapes LinkedIn job listings")
    def scrape_linkedin(job: str, location: str, signal=None) -> str:
        # raise signal.raise_if_aborted() at checkpoints
        ...
"""

from __future__ import annotations

import asyncio
import functools
import inspect
import threading
from dataclasses import dataclass, field
from typing import Any, Callable, Optional, get_type_hints


# ══════════════════════════════════════════════════════════════════════════════
#  Tool dataclass
# ══════════════════════════════════════════════════════════════════════════════


@dataclass
class Tool:
    """One callable tool in LaziBrain's registry."""

    name: str
    description: str
    func: Callable[..., Any]
    input_schema: dict = field(default_factory=dict)
    # Injected by @tool decorator at registration time
    param_names: tuple = field(default_factory=tuple)
    has_signal: bool = False

    def execute(self, input_data: dict, ctx: Optional[dict] = None) -> Any:
        """
        Call the tool with input_data kwargs + optional AbortSignal from ctx.

        ctx is None when called directly (no signal).
        When called via LaziBrain/ReAct loop, ctx = {"signal": abort_signal}.
        """
        import threading as _t

        # Build kwargs from input_data
        kwargs = {}
        for pname in self.param_names:
            if pname == "signal":
                continue  # signal comes from ctx, not input_data
            if pname in input_data:
                kwargs[pname] = input_data[pname]

        # Attach AbortSignal if provided
        signal = None
        if ctx and isinstance(ctx, dict):
            signal = ctx.get("signal")
        if signal is not None and self.has_signal:
            kwargs["signal"] = signal
        elif self.has_signal:
            # No signal in ctx — create a no-op that always returns False
            kwargs["signal"] = _NoOpAbortSignal()

        # Run in thread so Qt GUI never freezes
        result_holder: list = []

        def _call():
            try:
                result = self.func(**kwargs)
                result_holder.append(("ok", result))
            except AbortedError:
                result_holder.append(("aborted", "Tool execution aborted"))
            except Exception as exc:
                result_holder.append(("error", str(exc)))

        t = threading.Thread(target=_call, daemon=True)
        t.start()
        t.join(timeout=60)

        if not result_holder:
            return "[TIMEOUT] Tool did not return within 60 seconds"

        status, value = result_holder[0]
        if status == "ok":
            return value
        elif status == "aborted":
            raise AbortedError(value)
        else:
            raise ToolExecutionError(value)


class AbortedError(Exception):
    """Raised when a tool is cancelled via AbortSignal."""
    pass


class ToolExecutionError(Exception):
    """Raised when a tool raises an unhandled exception."""
    pass


class _NoOpAbortSignal:
    """A no-op signal used when ctx has no signal but the tool expects one."""

    def raise_if_aborted(self) -> None:
        pass


# ══════════════════════════════════════════════════════════════════════════════
#  Tool Registry
# ══════════════════════════════════════════════════════════════════════════════


_TOOL_REGISTRY: dict[str, Tool] = {}


def clear_tool_registry() -> None:
    """Clear all registered tools. Used in tests."""
    _TOOL_REGISTRY.clear()
    # Re-register the module-level built-in tools so clear_tool_registry
    # can be used between tests without losing the built-ins.
    _register_builtin_tools()


def get_tool_registry() -> dict[str, Tool]:
    return _TOOL_REGISTRY.copy()


def get_tool(name: str) -> Optional[Tool]:
    return _TOOL_REGISTRY.get(name)


def register_tool(
    name: str,
    description: str,
    input_schema: Optional[dict] = None,
) -> Callable:
    """
    Decorator that registers a function as a LaziBrain tool.

    Args:
        name: Tool name exposed to the LLM
        description: What the tool does (used in the system prompt)
        input_schema: JSON Schema for the tool's input parameters

    The decorated function receives an optional `signal: Optional[AbortSignal]`
    parameter. Call `signal.raise_if_aborted()` at checkpoints to support
    cancellation.

    Example:
        @register_tool(
            name="scrape_jobs",
            description="Scrapes jobs from a job board site",
            input_schema={
                "type": "object",
                "properties": {
                    "query": {"type": "string"},
                    "location": {"type": "string"},
                },
                "required": ["query"],
            },
        )
        def scrape_jobs(query: str, location: str = "Remote", signal=None) -> str:
            signal.raise_if_aborted()
            return f"Found 3 jobs for '{query}' in {location}"
    """
    def decorator(func: Callable) -> Callable:
        # Collect param names, detect if it takes a `signal` kwarg
        sig = inspect.signature(func)
        param_names = tuple(p.name for p in sig.parameters.values())
        has_signal = "signal" in param_names

        # Build schema from type hints if not provided
        schema = input_schema or {}
        if "properties" not in schema:
            try:
                hints = get_type_hints(func)
            except Exception:
                hints = {}
            properties = {}
            required = []
            for pname, p in sig.parameters.items():
                if pname == "signal":
                    continue
                if p.default is inspect.Parameter.empty:
                    required.append(pname)
                hint_name = hints.get(pname)
                py_type = "string"
                if hint_name in (int, "int"):
                    py_type = "integer"
                elif hint_name in (float, "float"):
                    py_type = "number"
                elif hint_name in (bool, "bool"):
                    py_type = "boolean"
                elif hint_name in (list, "list"):
                    py_type = "array"
                properties[pname] = {"type": py_type}
            schema = {
                "type": "object",
                "properties": properties,
                "required": required,
            }

        tool = Tool(
            name=name,
            description=description,
            func=func,
            input_schema=schema,
            param_names=param_names,
            has_signal=has_signal,
        )
        _TOOL_REGISTRY[name] = tool

        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            return func(*args, **kwargs)

        wrapper._tool = tool  # allow introspection
        return wrapper

    return decorator


# Convenience alias
tool = register_tool  # allow @tool(name=...) style


# ══════════════════════════════════════════════════════════════════════════════
#  Built-in helper tools (always available)
# ══════════════════════════════════════════════════════════════════════════════


def _done(success: bool, text: str = "", signal=None) -> str:
    """Placeholder — handled specially by LaziBrain ReAct loop."""
    return f"done: success={success}, text={text}"


def _ask_user(question: str, signal=None) -> str:
    """Placeholder — LaziBrain connects this to the Qt ask_user flow."""
    return f"[ask_user] {question}"


def _wait(seconds: int, signal=None) -> str:
    import time
    signal.raise_if_aborted()
    time.sleep(seconds)
    return f"Waited {seconds}s"


def _register_builtin_tools() -> None:
    """Re-register the 3 built-in tools. Called at module init and after
    clear_tool_registry() so tests that wipe the registry can still access them."""
    _TOOL_REGISTRY["done"] = Tool(
        name="done",
        description="Signals that the task is complete.",
        func=_done,
        input_schema={
            "type": "object",
            "properties": {
                "success": {"type": "boolean"},
                "text": {"type": "string"},
            },
            "required": ["success"],
        },
        param_names=("success", "text", "signal"),
        has_signal=True,
    )
    _TOOL_REGISTRY["ask_user"] = Tool(
        name="ask_user",
        description="Ask the user a question.",
        func=_ask_user,
        input_schema={
            "type": "object",
            "properties": {"question": {"type": "string"}},
            "required": ["question"],
        },
        param_names=("question", "signal"),
        has_signal=True,
    )
    _TOOL_REGISTRY["wait"] = Tool(
        name="wait",
        description="Wait for N seconds.",
        func=_wait,
        input_schema={
            "type": "object",
            "properties": {"seconds": {"type": "integer"}},
            "required": ["seconds"],
        },
        param_names=("seconds", "signal"),
        has_signal=True,
    )


_register_builtin_tools()
