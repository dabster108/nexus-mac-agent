"""Integration tests — these touch the real Mac and can launch an application.

Opt in explicitly::

    uv run pytest -m integration

They are excluded from the default run so that `uv run pytest` never opens
windows on a developer's machine.
"""

from __future__ import annotations

import sys

import pytest
from mcp import Client, StdioServerParameters, stdio_client

from nexus_mac_mcp.server import create_server
from nexus_mac_mcp.tools import applications

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(sys.platform != "darwin", reason="requires macOS"),
]

#: Ships with every Mac, opens instantly, and closing it costs nothing.
TEST_APPLICATION = "TextEdit"


async def test_the_server_runs_as_a_real_stdio_subprocess() -> None:
    """The transport the NEXUS backend actually uses."""
    params = StdioServerParameters(
        command=sys.executable, args=["-m", "nexus_mac_mcp"]
    )
    async with Client(stdio_client(params)) as client:
        tools = await client.list_tools()
        result = await client.call_tool("battery_status", {})

    assert {tool.name for tool in tools.tools} == {
        "battery_status",
        "system_info",
        "running_processes",
        "list_directory",
        "search_files",
        "read_file",
        "detect_workspace",
        "git_status",
        "git_branch",
        "git_log",
        "git_diff",
        "open_application",
        "run_command",
        "start_process",
        "list_processes",
        "process_status",
        "process_logs",
        "stop_process",
        "check_local_service",
        "list_memories",
        "get_memory",
        "save_memory",
        "delete_memory",
    }
    assert result.structured_content["success"] is True


def test_this_mac_has_discoverable_applications() -> None:
    found = applications.installed_applications()

    assert found, "no .app bundles found in the standard locations"
    assert any(app.name == "Safari" for app in found)


async def test_opening_a_real_application() -> None:
    """Actually launches TextEdit on this machine."""
    async with Client(create_server()) as client:
        result = await client.call_tool(
            "open_application", {"application": TEST_APPLICATION}
        )

    payload = result.structured_content
    assert payload["success"] is True, payload
    assert payload["application"] == TEST_APPLICATION
    assert payload["path"].endswith(f"{TEST_APPLICATION}.app")


async def test_memory_round_trips_through_a_real_subprocess(tmp_path) -> None:
    """The full path: real stdio subprocess, real SQLite file on disk."""
    import os

    db_path = tmp_path / "integration-nexus.db"
    params = StdioServerParameters(
        command=sys.executable,
        args=["-m", "nexus_mac_mcp"],
        env={**os.environ, "NEXUS_MAC_DB_PATH": str(db_path)},
    )

    async with Client(stdio_client(params)) as client:
        saved = await client.call_tool(
            "save_memory",
            {
                "type": "PROJECT",
                "key": "nexus_project",
                "value": {"name": "NEXUS", "path": str(tmp_path)},
            },
        )
        assert saved.structured_content["success"] is True

        listed = await client.call_tool("list_memories", {"query": "nexus"})
        assert listed.structured_content["count"] == 1

    assert db_path.exists()  # a real file was actually written


async def test_killing_the_mcp_server_stops_its_processes(tmp_path) -> None:
    """No orphaned development servers when the backend goes away."""
    import os
    import time

    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / "package.json").write_text('{"scripts": {"dev": "sleep 120"}}')

    params = StdioServerParameters(
        command=sys.executable,
        args=["-m", "nexus_mac_mcp"],
        env={
            **os.environ,
            "NEXUS_MAC_ALLOWED_ROOTS": str(workspace),
        },
    )

    pid = None
    async with Client(stdio_client(params)) as client:
        result = await client.call_tool(
            "start_process",
            {"command": "npm run dev", "working_directory": str(workspace)},
        )
        payload = result.structured_content
        assert payload["success"] is True, payload
        pid = payload["pid"]
        os.kill(pid, 0)  # alive while the server is up

    # Leaving the context shuts the server down; its child must go with it.
    for _ in range(50):
        time.sleep(0.1)
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return
    raise AssertionError(f"process {pid} outlived the MCP server")
