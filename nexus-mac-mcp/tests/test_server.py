"""The MCP surface: discovery, metadata and calling tools over the protocol."""

from __future__ import annotations

import sys

import pytest
from conftest import macos_only
from mcp import Client

from nexus_mac_mcp.core.permissions import META_NAMESPACE, Permission
from nexus_mac_mcp.core.platform import MACOS_REQUIRED_MESSAGE, require_macos
from nexus_mac_mcp.server import SERVER_NAME, create_server

EXPECTED_TOOLS = {
    # system
    "battery_status": Permission.SAFE,
    "system_info": Permission.SAFE,
    "running_processes": Permission.SAFE,
    # filesystem — read-only
    "list_directory": Permission.SAFE,
    "search_files": Permission.SAFE,
    "read_file": Permission.SAFE,
    # workspace
    "detect_workspace": Permission.SAFE,
    # git — read-only
    "git_status": Permission.SAFE,
    "git_branch": Permission.SAFE,
    "git_log": Permission.SAFE,
    "git_diff": Permission.SAFE,
    # processes — read-only views of what NEXUS started
    "list_processes": Permission.SAFE,
    "process_status": Permission.SAFE,
    "process_logs": Permission.SAFE,
    # local services
    "check_local_service": Permission.SAFE,
    # memory — read-only
    "list_memories": Permission.SAFE,
    "get_memory": Permission.SAFE,
    # things that change something — all gated by the backend
    "open_application": Permission.CONFIRM,
    "run_command": Permission.CONFIRM,
    "start_process": Permission.CONFIRM,
    "stop_process": Permission.CONFIRM,
    "save_memory": Permission.CONFIRM,
    "delete_memory": Permission.CONFIRM,
}


async def test_every_expected_tool_is_discoverable() -> None:
    async with Client(create_server()) as client:
        tools = await client.list_tools()

    assert {tool.name for tool in tools.tools} == set(EXPECTED_TOOLS)


async def test_each_tool_declares_its_permission() -> None:
    async with Client(create_server()) as client:
        tools = await client.list_tools()

    for tool in tools.tools:
        declared = (tool.meta or {}).get(META_NAMESPACE, {}).get("permission")
        assert declared == str(EXPECTED_TOOLS[tool.name]), tool.name


async def test_no_tool_declares_more_access_than_it_needs() -> None:
    async with Client(create_server()) as client:
        tools = await client.list_tools()

    by_name = {tool.name: tool for tool in tools.tools}
    # The only tool that changes anything about the Mac is the one that opens
    # an app; everything else must be SAFE.
    confirm = {
        name
        for name, tool in by_name.items()
        if (tool.meta or {}).get(META_NAMESPACE, {}).get("permission") == "CONFIRM"
    }
    assert confirm == {
        "open_application",
        "run_command",
        "start_process",
        "stop_process",
        "save_memory",
        "delete_memory",
    }


async def test_every_tool_is_described_for_the_model() -> None:
    async with Client(create_server()) as client:
        tools = await client.list_tools()

    for tool in tools.tools:
        assert tool.description and len(tool.description) > 20, tool.name


async def test_no_tool_offers_arbitrary_execution() -> None:
    async with Client(create_server()) as client:
        tools = await client.list_tools()

    names = {tool.name for tool in tools.tools}
    for forbidden in (
        "execute_command",
        "execute_anything",
        "run_shell",
        "terminal",
        "delete_file",
        "delete_directory",
        "write_file",
        "move_file",
        "copy_file",
        "create_directory",
        # Git tools are read-only; nothing that mutates a repository exists.
        "git_commit",
        "git_push",
        "git_checkout",
        "git_reset",
        "git_clean",
        "git_merge",
    ):
        assert forbidden not in names


@macos_only
async def test_calling_a_safe_tool_over_the_protocol() -> None:
    async with Client(create_server()) as client:
        result = await client.call_tool("system_info", {})

    assert not result.is_error
    assert result.structured_content["platform"] == "macOS"


@macos_only
async def test_battery_over_the_protocol() -> None:
    async with Client(create_server()) as client:
        result = await client.call_tool("battery_status", {})

    assert not result.is_error
    assert 0 <= result.structured_content["percentage"] <= 100


async def test_a_bad_argument_is_rejected_by_the_schema() -> None:
    async with Client(create_server()) as client:
        result = await client.call_tool("running_processes", {"limit": 99_999})

    # The schema caps it, so the server never sees an absurd value.
    assert result.is_error


async def test_open_application_reports_a_missing_app_without_launching() -> None:
    async with Client(create_server()) as client:
        result = await client.call_tool(
            "open_application", {"application": "NoSuchApplicationHere"}
        )

    assert not result.is_error  # a tool-level failure, not a protocol error
    assert result.structured_content == {
        "success": False,
        "error": "Application not found",
        "requested": "NoSuchApplicationHere",
    }


async def test_open_application_requires_a_name() -> None:
    async with Client(create_server()) as client:
        result = await client.call_tool("open_application", {"application": "  "})

    assert result.structured_content["error"] == "Application name is required"


def test_the_server_is_named_for_the_backend_to_find() -> None:
    assert SERVER_NAME == "nexus-mac"


def test_startup_refuses_to_run_off_macos(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sys, "platform", "linux")

    with pytest.raises(SystemExit) as excinfo:
        require_macos()

    assert str(excinfo.value) == MACOS_REQUIRED_MESSAGE


async def test_run_command_declares_an_approval_prompt() -> None:
    """The backend renders this for the user; a description would read poorly."""
    async with Client(create_server()) as client:
        tools = await client.list_tools()

    run_command = next(tool for tool in tools.tools if tool.name == "run_command")
    prompt = (run_command.meta or {})[META_NAMESPACE]["prompt"]

    assert prompt == "Run {command} in {working_directory}"
    assert prompt.format(command="pytest", working_directory="~/p") == "Run pytest in ~/p"


async def test_run_command_refuses_a_dangerous_command_over_the_protocol() -> None:
    async with Client(create_server()) as client:
        result = await client.call_tool(
            "run_command", {"command": "rm -rf /", "working_directory": "~"}
        )

    assert not result.is_error  # a tool-level refusal, not a protocol error
    assert result.structured_content["success"] is False
    assert result.structured_content["status"] == "rejected"


async def test_memory_type_argument_accepts_lowercase_from_the_model() -> None:
    """A live-observed failure: Groq's own schema validation rejected a
    lowercase type before the call ever reached our (already
    case-insensitive) Python parsing. The schema itself must accept it."""
    async with Client(create_server()) as client:
        result = await client.call_tool("list_memories", {"type": "project"})

    assert not result.is_error
    assert result.structured_content["success"] is True
