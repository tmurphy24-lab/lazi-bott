"""
Tests for Phase 2 components: tool_decorator, mcp_bridge, lazibrain_core.
Run with: pytest app/test_phase2.py -v
"""

import json
import subprocess
import sys
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))


# ══════════════════════════════════════════════════════════════════════════════
#  tool_decorator tests
# ══════════════════════════════════════════════════════════════════════════════


class TestToolDecorator:
    def setup_method(self):
        from app.tool_decorator import clear_tool_registry
        clear_tool_registry()

    def test_register_and_get(self):
        from app.tool_decorator import register_tool, get_tool

        @register_tool(
            name="test_tool",
            description="A test tool",
            input_schema={"type": "object", "properties": {"x": {"type": "integer"}}},
        )
        def my_tool(x: int, signal=None):
            return f"got {x}"

        tool = get_tool("test_tool")
        assert tool is not None
        assert tool.name == "test_tool"
        assert tool.description == "A test tool"
        assert tool.has_signal is True

    def test_registered_tools_dict_keys(self):
        from app.tool_decorator import register_tool, get_tool_registry

        @register_tool(name="tool_a", description="", input_schema={})
        def tool_a(signal=None): return "a"
        @register_tool(name="tool_b", description="", input_schema={})
        def tool_b(signal=None): return "b"

        registry = get_tool_registry()
        assert "tool_a" in registry
        assert "tool_b" in registry

    def test_execute_with_noop_signal(self):
        from app.tool_decorator import register_tool, get_tool

        @register_tool(name="exec_ok", description="", input_schema={})
        def my_tool(signal=None):
            signal.raise_if_aborted()  # no-op, should not raise
            return "success"

        tool = get_tool("exec_ok")
        result = tool.execute({}, ctx={})  # no signal in ctx → NoOpAbortSignal used
        assert result == "success"

    def test_execute_raises_aborted_error(self):
        from app.tool_decorator import register_tool, get_tool, AbortedError

        @register_tool(name="exec_abort", description="", input_schema={})
        def my_tool(signal=None):
            signal.raise_if_aborted()
            return "should not reach"

        tool = get_tool("exec_abort")

        class _MockAbort:
            def raise_if_aborted(self):
                raise AbortedError("user cancelled")

        # execute() should raise AbortedError when signal aborts
        with pytest.raises(AbortedError, match="Tool execution aborted"):
            tool.execute({}, ctx={"signal": _MockAbort()})

    def test_done_returns_string(self):
        from app.tool_decorator import get_tool

        tool = get_tool("done")
        assert tool is not None, "done tool should be pre-registered"
        result = tool.execute({"success": True, "text": "all done chief"}, ctx={})
        assert isinstance(result, str)
        assert "success=True" in result

    def test_ask_user_returns_string(self):
        from app.tool_decorator import get_tool

        tool = get_tool("ask_user")
        assert tool is not None, "ask_user tool should be pre-registered"
        result = tool.execute({"question": "Continue chief?"}, ctx={})
        assert isinstance(result, str)
        assert "ask_user" in result
        assert "Continue chief?" in result

    def test_wait_returns_string(self):
        from app.tool_decorator import get_tool

        tool = get_tool("wait")
        assert tool is not None, "wait tool should be pre-registered"
        result = tool.execute({"seconds": 0}, ctx={})
        assert isinstance(result, str)
        assert "Waited" in result

    def test_wait_with_abort(self):
        from app.tool_decorator import get_tool, AbortedError

        tool = get_tool("wait")

        class _MockAbort:
            def raise_if_aborted(self):
                raise AbortedError("abort!")

        # wait checks signal.raise_if_aborted() immediately, so it raises
        with pytest.raises(AbortedError):
            tool.execute({"seconds": 10}, ctx={"signal": _MockAbort()})

    def test_noop_abort_signal(self):
        from app.tool_decorator import _NoOpAbortSignal

        sig = _NoOpAbortSignal()
        sig.raise_if_aborted()  # must not raise

    def test_tool_wrapper_preserves_function(self):
        from app.tool_decorator import register_tool

        @register_tool(name="wrapper_test", description="", input_schema={})
        def my_func(signal=None): return 42

        # The wrapper should return the function's result
        assert my_func() == 42
        assert hasattr(my_func, "_tool")


# ══════════════════════════════════════════════════════════════════════════════
#  mcp_bridge tests
# ══════════════════════════════════════════════════════════════════════════════


class TestMCPServer:
    def test_server_creation(self):
        from app.mcp_bridge import MCPServer

        server = MCPServer("test-server", "1.0.0")
        assert server.name == "test-server"
        assert server.version == "1.0.0"
        assert server._running is False

    def test_server_tool_registration(self):
        from app.mcp_bridge import MCPServer

        server = MCPServer("test-server", "1.0.0")

        @server.tool(name="scrape", description="Scrape jobs", input_schema={})
        def scrape(**kwargs):
            return {"content": [{"type": "text", "text": "ok"}]}

        assert "scrape" in server._tools
        assert "scrape" in server._handlers

    def test_server_handle_initialize(self):
        from app.mcp_bridge import MCPServer, JSONRPCRequest

        server = MCPServer("test-server", "1.0.0")
        req = JSONRPCRequest(id=1, method="initialize", params={})
        resp = server._handle_request(req)
        assert resp.result is not None
        assert resp.result["serverInfo"]["name"] == "test-server"
        assert "capabilities" in resp.result

    def test_server_handle_tools_list(self):
        from app.mcp_bridge import MCPServer, JSONRPCRequest

        server = MCPServer("test-server", "1.0.0")

        @server.tool(name="job1", description="", input_schema={})
        def job1(**kw): return {"content": []}

        req = JSONRPCRequest(id=2, method="tools/list", params={})
        resp = server._handle_request(req)
        assert resp.result is not None
        tool_names = [t["name"] for t in resp.result["tools"]]
        assert "job1" in tool_names

    def test_server_handle_tools_call(self):
        from app.mcp_bridge import MCPServer, JSONRPCRequest

        server = MCPServer("test-server", "1.0.0")

        @server.tool(name="echo", description="", input_schema={
            "type": "object",
            "properties": {"msg": {"type": "string"}},
            "required": ["msg"],
        })
        def echo(msg: str):
            return {"content": [{"type": "text", "text": f"echo: {msg}"}]}

        req = JSONRPCRequest(
            id=3,
            method="tools/call",
            params={"name": "echo", "arguments": {"msg": "hello chief"}},
        )
        resp = server._handle_request(req)
        assert resp.result is not None
        content = resp.result["content"]
        assert any("hello chief" in str(c) for c in content)

    def test_server_handle_unknown_method(self):
        from app.mcp_bridge import MCPServer, JSONRPCRequest

        server = MCPServer("test-server", "1.0.0")
        req = JSONRPCRequest(id=4, method="not_a_real_method", params={})
        resp = server._handle_request(req)
        assert resp.error is not None
        assert resp.error["code"] == -32601  # METHOD_NOT_FOUND

    def test_server_handle_ping(self):
        from app.mcp_bridge import MCPServer, JSONRPCRequest

        server = MCPServer("test-server", "1.0.0")
        req = JSONRPCRequest(id=5, method="ping", params={})
        resp = server._handle_request(req)
        assert resp.result == {"pong": True}

    def test_server_handle_tools_call_not_found(self):
        from app.mcp_bridge import MCPServer, JSONRPCRequest

        server = MCPServer("test-server", "1.0.0")
        req = JSONRPCRequest(
            id=6, method="tools/call",
            params={"name": "nonexistent_tool", "arguments": {}},
        )
        resp = server._handle_request(req)
        assert resp.error is not None
        assert resp.error["code"] == -32601

    def test_mcp_bridge_stub_mode(self):
        from app.mcp_bridge import MCPBridge

        bridge = MCPBridge()  # No subprocess_cmd → stub mode
        assert bridge._stub_mode is True
        srv = bridge.create_server()
        assert srv is not None

    def test_server_stop(self):
        from app.mcp_bridge import MCPServer

        server = MCPServer("test-server", "1.0.0")
        server.stop()
        assert server._running is False


class TestMCPJSONRPC:
    def test_request_from_dict(self):
        from app.mcp_bridge import JSONRPCRequest

        req = JSONRPCRequest.from_dict({
            "jsonrpc": "2.0", "id": 42,
            "method": "tools/list", "params": {"foo": "bar"},
        })
        assert req.jsonrpc == "2.0"
        assert req.id == 42
        assert req.method == "tools/list"
        assert req.params == {"foo": "bar"}

    def test_request_from_dict_missing_fields(self):
        from app.mcp_bridge import JSONRPCRequest

        req = JSONRPCRequest.from_dict({"jsonrpc": "2.0"})
        assert req.method == ""
        assert req.id is None

    def test_response_to_json(self):
        from app.mcp_bridge import JSONRPCResponse

        resp = JSONRPCResponse(id=1, result={"tools": []})
        text = resp.to_json()
        parsed = json.loads(text)
        assert parsed["id"] == 1
        assert parsed["result"]["tools"] == []

    def test_response_to_json_with_error(self):
        from app.mcp_bridge import JSONRPCResponse, JSONRPCError

        err = JSONRPCError(code=-32601, message="Method not found")
        resp = JSONRPCResponse(id=5, error=err.to_dict())
        text = resp.to_json()
        parsed = json.loads(text)
        assert parsed["id"] == 5
        assert parsed["error"]["code"] == -32601

    def test_response_null_id_omitted(self):
        from app.mcp_bridge import JSONRPCResponse

        resp = JSONRPCResponse(id=None, result={"ok": True})
        text = resp.to_json()
        parsed = json.loads(text)
        assert "id" not in parsed  # null id omitted in JSON-RPC 2.0

    def test_mcp_tool_to_dict(self):
        from app.mcp_bridge import MCPTool

        t = MCPTool(name="test", description="A test",
                     input_schema={"type": "object"})
        d = t.to_mcp_dict()
        assert d["name"] == "test"
        assert d["inputSchema"] == {"type": "object"}

    def test_mcp_tool_call_result(self):
        from app.mcp_bridge import MCPToolCallResult

        r = MCPToolCallResult(
            content=[{"type": "text", "text": "hello"}],
            is_error=False,
        )
        d = r.to_mcp_dict()
        assert d["content"][0]["text"] == "hello"
        assert d["isError"] is False

    def test_error_codes(self):
        from app.mcp_bridge import (
            MCP_ERROR_PARSE, MCP_ERROR_INVALID_REQUEST,
            MCP_ERROR_METHOD_NOT_FOUND, MCP_ERROR_INVALID_PARAMS,
            MCP_ERROR_INTERNAL,
        )
        assert MCP_ERROR_PARSE == -32700
        assert MCP_ERROR_INVALID_REQUEST == -32600
        assert MCP_ERROR_METHOD_NOT_FOUND == -32601
        assert MCP_ERROR_INVALID_PARAMS == -32602
        assert MCP_ERROR_INTERNAL == -32603


# ══════════════════════════════════════════════════════════════════════════════
#  lazibrain_core tests — skip without PySide6
# ══════════════════════════════════════════════════════════════════════════════


class TestLaziBrainCore:
    @pytest.fixture(autouse=True)
    def _require_pyside6(self):
        try:
            from PySide6.QtCore import QObject  # noqa
        except Exception:
            pytest.skip("PySide6 not available")

    def test_agent_status_enum(self):
        from app.lazibrain_core import AgentStatus

        assert AgentStatus.IDLE.value == "idle"
        assert AgentStatus.RUNNING.value == "running"
        assert AgentStatus.COMPLETED.value == "completed"
        assert AgentStatus.ERROR.value == "error"
        assert AgentStatus.STOPPED.value == "stopped"

    def test_history_event(self):
        from app.lazibrain_core import HistoryEvent

        evt = HistoryEvent(type="step", step=1, content="test observation")
        assert evt.type == "step"
        assert evt.step == 1
        assert evt.content == "test observation"

    def test_agent_activity(self):
        from app.lazibrain_core import AgentActivity

        act = AgentActivity(
            type="thinking",
            tool="easyapplyjobsbot",
            message="Scraping jobs...",
        )
        assert act.type == "thinking"
        assert act.tool == "easyapplyjobsbot"

    def test_core_instantiate(self):
        from PySide6.QtWidgets import QApplication
        from app.lazibrain_core import LaziBrainCore

        app = QApplication.instance() or QApplication([])
        core = LaziBrainCore()
        assert core._status == "idle"
        app.quit()

    def test_core_configure(self):
        from PySide6.QtWidgets import QApplication
        from app.lazibrain_core import LaziBrainCore

        app = QApplication.instance() or QApplication([])
        core = LaziBrainCore()
        core.configure("openai", "sk-test")
        assert core._provider == "openai"
        assert core._api_key == "sk-test"
        app.quit()


class TestLaziBotEngineToolsRegistered:
    @pytest.fixture(autouse=True)
    def _require_pyside6(self):
        try:
            from PySide6.QtCore import QObject  # noqa
        except Exception:
            pytest.skip("PySide6 not available")

    def test_all_6_engines_in_registry(self):
        from app.tool_decorator import get_tool_registry

        registry = get_tool_registry()
        for eng in [
            "easyapplyjobsbot", "linkedin_aihawk", "auto_job_applier",
            "linkedin_bot", "job_apply_ai_agent", "page_agent",
        ]:
            assert eng in registry, f"{eng} not registered"

    def test_engine_tools_have_descriptions(self):
        from app.tool_decorator import get_tool_registry

        registry = get_tool_registry()
        for name in ["easyapplyjobsbot", "linkedin_aihawk", "page_agent"]:
            tool = registry[name]
            assert tool.description, f"{name} has no description"
            assert len(tool.description) > 10
