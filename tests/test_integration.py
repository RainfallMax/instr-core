"""Integration tests for the instr-core MCP server over stdio transport.

These tests spawn the server as a subprocess and speak real JSON-RPC over
stdin/stdout, exercising the full stack rather than calling internal functions.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

import pytest

FIXTURES_ROOT = Path(__file__).parent / "fixtures" / "registry"


class McpStdioClient:
    """A thin JSON-RPC client that speaks to an MCP server over stdio."""

    def __init__(self, proc: subprocess.Popen) -> None:
        self.proc = proc
        self._msg_id = 0
        self._buffer = b""

    def _next_id(self) -> int:
        self._msg_id += 1
        return self._msg_id

    def _send(self, payload: dict[str, Any]) -> None:
        data = json.dumps(payload).encode("utf-8")
        self.proc.stdin.write(data + b"\n")
        self.proc.stdin.flush()

    def _recv(self) -> dict[str, Any]:
        """Read one JSON-RPC message from the server's stdout."""
        deadline = time.monotonic() + 10.0
        while time.monotonic() < deadline:
            try:
                raw = self.proc.stdout.readline()
            except Exception:
                raw = b""
            if raw:
                try:
                    return json.loads(raw.decode("utf-8"))
                except json.JSONDecodeError:
                    continue
            time.sleep(0.01)
        raise TimeoutError("Did not receive a response from the MCP server")

    def initialize(self) -> dict[str, Any]:
        """Send the MCP initialize handshake."""
        self._send(
            {
                "jsonrpc": "2.0",
                "id": self._next_id(),
                "method": "initialize",
                "params": {
                    "protocolVersion": "2024-11-05",
                    "capabilities": {},
                    "clientInfo": {"name": "test-client", "version": "0.1.0"},
                },
            }
        )
        return self._recv()

    def send_notification(self, method: str, params: dict[str, Any] | None = None) -> None:
        """Send a JSON-RPC notification (no response expected)."""
        payload: dict[str, Any] = {"jsonrpc": "2.0", "method": method}
        if params is not None:
            payload["params"] = params
        self._send(payload)

    def call_tool(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        """Call an MCP tool and return the result."""
        self._send(
            {
                "jsonrpc": "2.0",
                "id": self._next_id(),
                "method": "tools/call",
                "params": {"name": name, "arguments": arguments},
            }
        )
        return self._recv()

    def list_tools(self) -> dict[str, Any]:
        """List available tools."""
        self._send(
            {
                "jsonrpc": "2.0",
                "id": self._next_id(),
                "method": "tools/list",
                "params": {},
            }
        )
        return self._recv()

    def list_resources(self) -> dict[str, Any]:
        """List available resources."""
        self._send(
            {
                "jsonrpc": "2.0",
                "id": self._next_id(),
                "method": "resources/list",
                "params": {},
            }
        )
        return self._recv()

    def read_resource(self, uri: str) -> dict[str, Any]:
        """Read a resource by URI."""
        self._send(
            {
                "jsonrpc": "2.0",
                "id": self._next_id(),
                "method": "resources/read",
                "params": {"uri": uri},
            }
        )
        return self._recv()

    def close(self) -> None:
        """Terminate the server subprocess."""
        try:
            self.proc.stdin.close()
        except Exception:
            pass
        try:
            self.proc.terminate()
            self.proc.wait(timeout=5.0)
        except subprocess.TimeoutExpired:
            self.proc.kill()
            self.proc.wait()


@pytest.fixture
def mcp_client():
    """Yield an McpStdioClient connected to a live server process."""
    # Determine how to launch the server. Prefer the installed entry-point,
    # but fall back to running the module directly.
    env = os.environ.copy()
    env["INSTR_CORE_REGISTRY"] = str(FIXTURES_ROOT)

    cmd = [sys.executable, "-m", "instr_core.main"]
    proc = subprocess.Popen(
        cmd,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=env,
        text=False,
    )
    client = McpStdioClient(proc)
    try:
        yield client
    finally:
        client.close()


class TestMcpLifecycle:
    def test_initialize(self, mcp_client: McpStdioClient) -> None:
        result = mcp_client.initialize()
        assert "result" in result
        server_info = result["result"]["serverInfo"]
        assert server_info["name"] == "instr-core"

    def test_list_tools(self, mcp_client: McpStdioClient) -> None:
        mcp_client.initialize()
        result = mcp_client.list_tools()
        assert "result" in result
        tools = result["result"]["tools"]
        names = {t["name"] for t in tools}
        expected = {
            "server_status",
            "validate_instrument_state",
            "list_instruments",
            "search_instruments",
            "get_command_tree",
            "get_safety_limits",
            "get_command_detail",
            "validate_command_sequence",
        }
        assert expected.issubset(names)

    def test_list_resources(self, mcp_client: McpStdioClient) -> None:
        mcp_client.initialize()
        result = mcp_client.list_resources()
        assert "result" in result
        resources = result["result"]["resources"]
        uris = {r["uri"] for r in resources}
        assert "instr://keithley/smu/2600" in uris

    def test_read_resource(self, mcp_client: McpStdioClient) -> None:
        mcp_client.initialize()
        result = mcp_client.read_resource("instr://keithley/smu/2600")
        assert "result" in result
        contents = result["result"]["contents"]
        assert len(contents) == 1
        text = contents[0]["content"]
        assert "Keithley" in text
        assert "2600" in text

    def test_read_resource_not_found(self, mcp_client: McpStdioClient) -> None:
        mcp_client.initialize()
        result = mcp_client.read_resource("instr://nonexistent/model/xyz")
        assert "error" in result
        assert "not found" in result["error"]["message"].lower() or "not in the registry" in result["error"]["message"].lower()


class TestToolCalls:
    def test_server_status(self, mcp_client: McpStdioClient) -> None:
        mcp_client.initialize()
        result = mcp_client.call_tool("server_status", {})
        assert "result" in result
        text = result["result"]["content"][0]["text"]
        assert "instr-core" in text
        assert "healthy" in text

    def test_list_instruments(self, mcp_client: McpStdioClient) -> None:
        mcp_client.initialize()
        result = mcp_client.call_tool("list_instruments", {})
        assert "result" in result
        text = result["result"]["content"][0]["text"]
        assert "keithley/smu/2600" in text

    def test_validate_instrument_state_pass(self, mcp_client: McpStdioClient) -> None:
        mcp_client.initialize()
        result = mcp_client.call_tool(
            "validate_instrument_state",
            {
                "instrument": "keithley/smu/2600",
                "command": ":SOUR:FUNC",
                "argument": "VOLT",
                "current_state": {"output": "OFF"},
            },
        )
        assert "result" in result
        text = result["result"]["content"][0]["text"]
        assert "PASS" in text

    def test_validate_instrument_state_fail(self, mcp_client: McpStdioClient) -> None:
        mcp_client.initialize()
        result = mcp_client.call_tool(
            "validate_instrument_state",
            {
                "instrument": "keithley/smu/2600",
                "command": ":OUTP",
                "argument": "ON",
                "current_state": {},
            },
        )
        assert "result" in result
        text = result["result"]["content"][0]["text"]
        assert "FAIL" in text
        assert "Compliance must be configured" in text

    def test_get_safety_limits(self, mcp_client: McpStdioClient) -> None:
        mcp_client.initialize()
        result = mcp_client.call_tool(
            "get_safety_limits", {"instrument": "keithley/smu/2600"}
        )
        assert "result" in result
        text = result["result"]["content"][0]["text"]
        assert "40" in text
        assert "3.0" in text

    def test_validate_command_sequence(self, mcp_client: McpStdioClient) -> None:
        mcp_client.initialize()
        result = mcp_client.call_tool(
            "validate_command_sequence",
            {
                "instrument": "keithley/smu/2600",
                "commands": [
                    {"command": ":SENS:CURR:PROT", "argument": "0.01"},
                    {"command": ":OUTP", "argument": "ON"},
                ],
            },
        )
        assert "result" in result
        text = result["result"]["content"][0]["text"]
        assert "ALL PASS" in text
