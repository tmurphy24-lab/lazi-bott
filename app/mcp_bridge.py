"""
MCP Bridge — Lazi-Bot Phase 2
===============================
Minimal MCP (Model Context Protocol) server that LaziBrain hosts.

page-agent is the MCP client — it connects to this server over stdio.
LaziBrain registers tools here; page-agent calls them through MCP.

MCP Spec: https://modelcontextprotocol.io/specification
Transport: JSON-RPC 2.0 over stdio (Windows-compatible).

Minimal implementation — no external dependencies.
"""

from __future__ import annotations

import json
import sys
import threading
import uuid
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from typing import Any, Optional


# ══════════════════════════════════════════════════════════════════════════════
#  JSON-RPC Types
# ══════════════════════════════════════════════════════════════════════════════


@dataclass
class JSONRPCRequest:
    jsonrpc: str = "2.0"
    id: Optional[str | int] = None
    method: str = ""
    params: dict = field(default_factory=dict)

    @staticmethod
    def from_dict(d: dict) -> "JSONRPCRequest":
        return JSONRPCRequest(
            jsonrpc=d.get("jsonrpc", "2.0"),
            id=d.get("id"),
            method=d.get("method", ""),
            params=d.get("params", {}),
        )


@dataclass
class JSONRPCResponse:
    jsonrpc: str = "2.0"
    id: Optional[str | int] = None
    result: Optional[dict] = None
    error: Optional[dict] = None

    def to_json(self) -> str:
        d = {"jsonrpc": self.jsonrpc}
        if self.id is not None:
            d["id"] = self.id
        if self.error is not None:
            d["error"] = self.error
        elif self.result is not None:
            d["result"] = self.result
        return json.dumps(d)


@dataclass
class JSONRPCError:
    code: int
    message: str
    data: Optional[Any] = None

    def to_dict(self) -> dict:
        d = {"code": self.code, "message": self.message}
        if self.data is not None:
            d["data"] = self.data
        return d


# ── Error codes ──────────────────────────────────────────────────────────────
MCP_ERROR_PARSE = -32700
MCP_ERROR_INVALID_REQUEST = -32600
MCP_ERROR_METHOD_NOT_FOUND = -32601
MCP_ERROR_INVALID_PARAMS = -32602
MCP_ERROR_INTERNAL = -32603


# ══════════════════════════════════════════════════════════════════════════════
#  MCP Tool definitions
# ══════════════════════════════════════════════════════════════════════════════


@dataclass
class MCPTool:
    name: str
    description: str
    input_schema: dict

    def to_mcp_dict(self) -> dict:
        return {
            "name": self.name,
            "description": self.description,
            "inputSchema": self.input_schema,
        }


@dataclass
class MCPToolCallResult:
    content: list[dict]
    is_error: bool = False

    def to_mcp_dict(self) -> dict:
        return {
            "content": self.content,
            "isError": self.is_error,
        }


# ══════════════════════════════════════════════════════════════════════════════
#  MCP Server — hosts tools, speaks JSON-RPC over stdio
# ══════════════════════════════════════════════════════════════════════════════


class MCPServer:
    """
    Minimal MCP server. Receives JSON-RPC requests from page-agent over stdin,
    dispatches to registered tools, writes responses to stdout.

    Thread-safe: can register tools from any thread; stdio I/O happens
    on the thread that calls run().

    Usage:
        server = MCPServer("lazi-brain")

        @server.tool(name="scrape_linkedin", description="...", input_schema={...})
        def scrape_linkedin(query: str, location: str):
            return {"jobs": [...]}

        server.run()   # blocks — run on background thread
    """

    def __init__(self, name: str, version: str = "1.0.0"):
        self.name = name
        self.version = version
        self._tools: dict[str, dict] = {}  # name -> tool def
        self._handlers: dict[str, callable] = {}  # name -> Python callable
        self._running = False
        self._lock = threading.Lock()

    # ── Tool registration ───────────────────────────────────────────────────

    def tool(
        self,
        name: str,
        description: str = "",
        input_schema: Optional[dict] = None,
    ) -> callable:
        """
        Decorator to register a tool with the MCP server.

        The decorated function receives **kwargs matching the input_schema.
        It must return a dict with a "content" list (MCP content block format).

        Example:
            @server.tool(name="scrape_jobs", description="Scrapes job listings", input_schema={
                "type": "object",
                "properties": {
                    "query": {"type": "string"},
                    "location": {"type": "string"},
                },
                "required": ["query"],
            })
            def scrape_jobs(**kwargs):
                return {"content": [{"type": "text", "text": "Found 3 jobs"}]}
        """
        def decorator(func: callable) -> callable:
            with self._lock:
                self._tools[name] = {
                    "name": name,
                    "description": description,
                    "inputSchema": input_schema or {},
                }
                self._handlers[name] = func
            return func
        return decorator

    # ── Protocol handlers ───────────────────────────────────────────────────

    def _handle_request(self, req: JSONRPCRequest) -> JSONRPCResponse:
        """Dispatch a single JSON-RPC request to the appropriate handler."""
        try:
            if req.method == "initialize":
                return self._handle_initialize(req)
            elif req.method == "tools/list":
                return self._handle_tools_list(req)
            elif req.method == "tools/call":
                return self._handle_tools_call(req)
            elif req.method == "ping":
                return JSONRPCResponse(id=req.id, result={"pong": True})
            else:
                return JSONRPCResponse(
                    id=req.id,
                    error=JSONRPCError(
                        MCP_ERROR_METHOD_NOT_FOUND,
                        f"Unknown method: {req.method}",
                    ).to_dict(),
                )
        except Exception as exc:
            return JSONRPCResponse(
                id=req.id,
                error=JSONRPCError(MCP_ERROR_INTERNAL, str(exc)).to_dict(),
            )

    def _handle_initialize(self, req: JSONRPCRequest) -> JSONRPCResponse:
        params = req.params
        return JSONRPCResponse(
            id=req.id,
            result={
                "protocolVersion": "2024-11-05",
                "serverInfo": {
                    "name": self.name,
                    "version": self.version,
                },
                "capabilities": {
                    "tools": {"listChanged": False},
                },
                "instructions": (
                    "Lazi-Bot MCP Bridge. Use tools/list to see available tools. "
                    "Call tools/call to execute a tool. Powered by LaziBrain."
                ),
            },
        )

    def _handle_tools_list(self, req: JSONRPCRequest) -> JSONRPCResponse:
        with self._lock:
            tools_list = list(self._tools.values())
        return JSONRPCResponse(
            id=req.id,
            result={"tools": tools_list},
        )

    def _handle_tools_call(self, req: JSONRPCRequest) -> JSONRPCResponse:
        params = req.params
        tool_name = params.get("name", "")
        arguments = params.get("arguments", {})

        with self._lock:
            if tool_name not in self._handlers:
                return JSONRPCResponse(
                    id=req.id,
                    error=JSONRPCError(
                        MCP_ERROR_METHOD_NOT_FOUND,
                        f"Tool not found: {tool_name}",
                    ).to_dict(),
                )
            handler = self._handlers[tool_name]

        try:
            result = handler(**arguments)

            # Normalize to MCP content block format
            if isinstance(result, dict) and "content" in result:
                content = result["content"]
                is_error = result.get("isError", False)
            else:
                content = [{"type": "text", "text": str(result)}]
                is_error = False

            return JSONRPCResponse(
                id=req.id,
                result=MCPToolCallResult(
                    content=content, is_error=is_error
                ).to_mcp_dict(),
            )
        except Exception as exc:
            return JSONRPCResponse(
                id=req.id,
                result=MCPToolCallResult(
                    content=[{"type": "text", "text": f"Error: {exc}"}],
                    is_error=True,
                ).to_mcp_dict(),
            )

    # ── Main I/O loop ─────────────────────────────────────────────────────

    def run(self) -> None:
        """
        Read JSON-RPC requests from stdin, write responses to stdout.
        Blocks the calling thread. Run on a background thread.
        """
        self._running = True
        reader = sys.stdin

        while self._running:
            try:
                line = reader.readline()
                if not line:
                    break  # EOF — stdin closed
                line = line.strip()
                if not line:
                    continue

                req = JSONRPCRequest.from_dict(json.loads(line))
                resp = self._handle_request(req)
                output = resp.to_json()
                sys.stdout.write(output + "\n")
                sys.stdout.flush()

            except json.JSONDecodeError as exc:
                err_resp = JSONRPCResponse(
                    error=JSONRPCError(
                        MCP_ERROR_PARSE,
                        f"Invalid JSON: {exc}",
                    ).to_dict(),
                )
                sys.stdout.write(err_resp.to_json() + "\n")
                sys.stdout.flush()
            except Exception as exc:
                err_resp = JSONRPCResponse(
                    error=JSONRPCError(MCP_ERROR_INTERNAL, str(exc)).to_dict(),
                )
                sys.stdout.write(err_resp.to_json() + "\n")
                sys.stdout.flush()

    def stop(self) -> None:
        self._running = False


# ══════════════════════════════════════════════════════════════════════════════
#  MCP Bridge — LaziBrain's connection to page-agent
# ══════════════════════════════════════════════════════════════════════════════


@dataclass
class MCPToolResult:
    """Result of calling a tool via the MCP Bridge."""
    success: bool
    content: list[dict]  # MCP content blocks
    error: Optional[str] = None

    @property
    def text(self) -> str:
        """Flatten content blocks to a single string."""
        return " ".join(
            block.get("text", "") for block in self.content if block.get("type") == "text"
        )


class MCPBridge:
    """
    LaziBrain's connection to page-agent via MCP.

    LaziBrain calls `mcp_bridge.call_tool("tool_name", {...})` to execute
    a tool in the browser (via page-agent). page-agent handles the DOM work
    and returns structured results.

    Transport: subprocess (page-agent.js running in Node.js or browser).
    Fallback: if page-agent is not available, tools return a graceful error.

    Usage:
        bridge = MCPBridge()
        result = await bridge.call_tool("navigate", {"url": "https://linkedin.com"})
        print(result.text)
    """

    def __init__(self, subprocess_cmd: Optional[list[str]] = None):
        """
        Args:
            subprocess_cmd: Command to launch page-agent subprocess.
                          e.g. ["node", "page-agent.js", "--transport", "stdio"]
                          If None, MCP bridge runs in a "stub" mode that returns
                          canned responses (for testing/dev without page-agent).
        """
        self._cmd = subprocess_cmd
        self._server: Optional[MCPServer] = None
        self._proc: Optional[Any] = None  # subprocess.Popen
        self._stub_mode = subprocess_cmd is None

    # ── Server-side: tools that page-agent can call ─────────────────────────

    def create_server(self) -> MCPServer:
        """Create and configure the MCP server that LaziBrain hosts."""
        server = MCPServer("lazi-brain-mcp", "1.0.0")

        # ── Tools page-agent uses to report back ──────────────────────────

        @server.tool(
            name="report_jobs",
            description="Report scraped job listings back to LaziBrain",
            input_schema={
                "type": "object",
                "properties": {
                    "jobs": {
                        "type": "array",
                        "items": {"type": "object"},
                        "description": "List of scraped job objects",
                    },
                    "source": {"type": "string", "description": "e.g. linkedin, indeed"},
                    "url": {"type": "string", "description": "Page URL jobs were scraped from"},
                },
                "required": ["jobs", "source"],
            },
        )
        def report_jobs(**kwargs) -> dict:
            """Called by page-agent after scraping a job listing page."""
            return {
                "content": [
                    {
                        "type": "text",
                        "text": f"Reported {len(kwargs.get('jobs', []))} jobs from {kwargs.get('source', 'unknown')}",
                    }
                ]
            }

        @server.tool(
            name="report_status",
            description="Report a status message back to LaziBrain",
            input_schema={
                "type": "object",
                "properties": {
                    "message": {"type": "string"},
                    "level": {"type": "string", "enum": ["info", "warn", "error"]},
                },
                "required": ["message"],
            },
        )
        def report_status(**kwargs) -> dict:
            """Called by page-agent to report progress."""
            return {"content": [{"type": "text", "text": f"[{kwargs.get('level', 'info')}] {kwargs.get('message', '')}"}]}

        self._server = server
        return server

    def start_server(self, background: bool = True) -> None:
        """
        Start the MCP server. Runs in background by default.

        If background=True, starts on a daemon thread and returns immediately.
        If background=False, blocks (call from background thread only).
        """
        if self._server is None:
            self.create_server()

        if background:
            t = threading.Thread(target=self._server.run, daemon=True, name="mcp-server")
            t.start()
        else:
            self._server.run()

    def stop_server(self) -> None:
        if self._server:
            self._server.stop()

    # ── Client-side: tools LaziBrain calls on page-agent ───────────────────

    async def call_tool(self, tool_name: str, arguments: dict) -> MCPToolResult:
        """
        Call a tool on page-agent via MCP (JSON-RPC over subprocess stdin/stdout).

        This is the "MCP client" side — LaziBrain calls this to ask page-agent
        to do DOM work in the browser.

        Args:
            tool_name: The tool to call (e.g. "navigate", "extract_jobs")
            arguments: Tool arguments dict

        Returns:
            MCPToolResult with success/content/error

        Note:
            In stub mode (no subprocess_cmd), returns a canned response so
            LaziBrain can function during development without page-agent running.
        """
        if self._stub_mode:
            return self._stub_result(tool_name, arguments)

        if self._proc is None or self._proc.poll() is not None:
            return MCPToolResult(
                success=False,
                content=[],
                error="page-agent subprocess not running. Start it first.",
            )

        req_id = str(uuid.uuid4())
        request = JSONRPCRequest(
            id=req_id,
            method="tools/call",
            params={"name": tool_name, "arguments": arguments},
        )

        try:
            self._proc.stdin.write(request.to_json() + "\n")
            self._proc.stdin.flush()

            # Read response
            response_line = self._proc.stdout.readline()
            if not response_line:
                return MCPToolResult(
                    success=False, content=[], error="page-agent closed stdin"
                )

            resp = JSONRPCResponse.from_dict(json.loads(response_line.strip()))
            if resp.error:
                return MCPToolResult(
                    success=False,
                    content=[],
                    error=resp.error.get("message", str(resp.error)),
                )
            return MCPToolResult(
                success=True,
                content=resp.result.get("content", []),
            )
        except Exception as exc:
            return MCPToolResult(success=False, content=[], error=str(exc))

    def launch_page_agent(self, node_path: str = "node") -> bool:
        """
        Launch page-agent as a subprocess connected to our MCP stdin/stdout.

        Args:
            node_path: Path to Node.js executable. Defaults to "node" on PATH.

        Returns:
            True if launched successfully, False otherwise.
        """
        if self._stub_mode or self._cmd is None:
            return False

        import subprocess

        try:
            self._proc = subprocess.Popen(
                self._cmd,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
            return True
        except FileNotFoundError:
            return False

    # ── Stub mode (dev / testing without page-agent) ───────────────────────

    def _stub_result(self, tool_name: str, arguments: dict) -> MCPToolResult:
        """Return canned responses when page-agent is not available."""
        stubs = {
            "navigate": "Navigated to page",
            "extract_jobs": (
                f"Stub: would extract jobs from {arguments.get('url', 'unknown')}. "
                "Install page-agent to enable real extraction."
            ),
            "click_apply": "Stub: would click Apply button",
            "fill_form": "Stub: would fill form fields",
            "get_page_html": "Stub: would return page HTML",
        }
        text = stubs.get(tool_name, f"Stub: tool '{tool_name}' called with {arguments}")
        return MCPToolResult(
            success=True,
            content=[{"type": "text", "text": text}],
        )

    @property
    def is_connected(self) -> bool:
        """True if the page-agent subprocess is running."""
        if self._stub_mode:
            return True  # stub always "connected"
        return self._proc is not None and self._proc.poll() is None

    def __repr__(self) -> str:
        mode = "stub" if self._stub_mode else "live"
        return f"<MCPBridge mode={mode} connected={self.is_connected}>"
