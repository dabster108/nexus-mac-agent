"""MCP integration against the NEXUS Mac MCP server.

These spawn the real server (the ``nexus-mac-mcp`` project) over stdio, so they
cover the whole path: MCP client -> MCP server -> tool -> result.
"""

from __future__ import annotations

import sys
from contextlib import AsyncExitStack

import pytest

from app.core.config import BACKEND_ROOT, Settings
from app.core.errors import MCPError
from app.mcp.client import MCPClient, MCPServerConfig
from app.mcp.registry import MCPServerRegistry, MCPToolSource
from app.tools.permissions import PermissionLevel
from app.tools.registry import ToolRegistry


def mac_server(settings: Settings) -> MCPServerConfig:
    return MCPServerRegistry.from_settings(settings).servers[0]


async def test_the_client_lists_the_mac_tools(settings: Settings) -> None:
    async with MCPClient(mac_server(settings)).session() as session:
        tools = await session.list_tools()

    names = {tool.name for tool in tools}
    assert names == {
        "battery_status",
        "system_info",
        "running_processes",
        "list_directory",
        "search_files",
        "read_file",
        "detect_workspace",
        "repo_overview",
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
        "verify_memory",
        "save_memory",
        "delete_memory",
    }


async def test_a_tool_call_returns_a_result(settings: Settings) -> None:
    async with MCPClient(mac_server(settings)).session() as session:
        result = await session.call_tool("system_info", {})

    assert not result.is_error
    assert result.structured is not None
    assert result.structured["platform"] == "macOS"
    assert result.structured["architecture"]


async def test_tools_arrive_with_their_permission_level(settings: Settings) -> None:
    async with MCPClient(mac_server(settings)).session() as session:
        source = MCPToolSource(session)
        definitions = {tool.name: tool for tool in await source.list_tools()}

    safe = {
        "list_processes",
        "process_status",
        "process_logs",
        "check_local_service",
        "battery_status",
        "system_info",
        "running_processes",
        "list_directory",
        "search_files",
        "read_file",
        "detect_workspace",
        "repo_overview",
        "git_status",
        "git_branch",
        "git_log",
        "git_diff",
    }
    for name in safe:
        assert definitions[name].permission is PermissionLevel.SAFE, name
    # Declared CONFIRM by the server, so the approval broker gates them.
    assert definitions["open_application"].permission is PermissionLevel.CONFIRM
    assert definitions["run_command"].permission is PermissionLevel.CONFIRM
    assert definitions["start_process"].permission is PermissionLevel.CONFIRM
    assert definitions["stop_process"].permission is PermissionLevel.CONFIRM
    assert definitions["battery_status"].source == "nexus-mac"


async def test_the_registry_runs_a_real_mcp_tool(settings: Settings) -> None:
    async with AsyncExitStack() as stack:
        sources = await MCPServerRegistry.from_settings(settings).open_sources(stack)
        registry = ToolRegistry(sources)
        await registry.refresh()

        result = await registry.call("system_info", {})

    assert not result.is_error
    assert result.metadata["source"] == "nexus-mac"


async def test_an_unreachable_server_raises_mcp_error() -> None:
    config = MCPServerConfig(
        name="broken", command=sys.executable, args=("-c", "raise SystemExit(1)")
    )

    with pytest.raises(MCPError, match="MCP server 'broken'"):
        async with MCPClient(config).session() as session:
            await session.list_tools()


async def test_a_missing_executable_raises_mcp_error() -> None:
    config = MCPServerConfig(name="ghost", command="definitely-not-a-real-binary")

    with pytest.raises(MCPError, match="Could not connect to MCP server 'ghost'"):
        async with MCPClient(config).session():
            pass


@pytest.mark.skipif(sys.platform != "darwin", reason="battery_status is macOS-only")
async def test_battery_status_on_macos(settings: Settings) -> None:
    async with MCPClient(mac_server(settings)).session() as session:
        result = await session.call_tool("battery_status", {})

    assert not result.is_error
    payload = result.structured
    assert payload["success"] is True
    assert 0 <= payload["percentage"] <= 100
    assert isinstance(payload["charging"], bool)


# --- the permission boundary holds across the new tools --------------------


async def test_read_only_tools_never_ask_for_approval(settings: Settings) -> None:
    """SAFE tools must run without a permission request appearing."""
    from contextlib import AsyncExitStack

    from app.agent.approvals import ApprovalBroker
    from app.tools.permissions import PermissionPolicy

    broker = ApprovalBroker()
    policy = PermissionPolicy()

    async with AsyncExitStack() as stack:
        sources = await MCPServerRegistry.from_settings(settings).open_sources(stack)
        registry = ToolRegistry(sources)
        await registry.refresh()

        for name in (
            "battery_status",
            "system_info",
            "running_processes",
            "list_directory",
            "search_files",
            "read_file",
            "detect_workspace",
            "repo_overview",
            "git_status",
            "git_branch",
            "git_log",
            "git_diff",
            "list_processes",
            "process_status",
            "process_logs",
            "check_local_service",
        ):
            decision = policy.evaluate(name, registry.require(name).permission)
            assert decision.allowed is True, name
            assert decision.requires_confirmation is False, name

    assert broker.list_pending() == []


async def test_the_application_tool_still_requires_approval(settings: Settings) -> None:
    from contextlib import AsyncExitStack

    from app.tools.permissions import PermissionPolicy

    async with AsyncExitStack() as stack:
        sources = await MCPServerRegistry.from_settings(settings).open_sources(stack)
        registry = ToolRegistry(sources)
        await registry.refresh()

        decision = PermissionPolicy().evaluate(
            "open_application", registry.require("open_application").permission
        )

    assert decision.allowed is False
    assert decision.requires_confirmation is True


async def test_every_discovered_tool_is_classified(settings: Settings) -> None:
    """Nothing arrives unclassified — an unknown tool would default to RESTRICTED."""
    from contextlib import AsyncExitStack

    async with AsyncExitStack() as stack:
        sources = await MCPServerRegistry.from_settings(settings).open_sources(stack)
        registry = ToolRegistry(sources)
        await registry.refresh()
        tools = registry.list_tools()

    assert len(tools) == 25
    assert all(tool.permission in PermissionLevel for tool in tools)
    assert not [tool for tool in tools if tool.permission is PermissionLevel.RESTRICTED]


async def test_a_real_filesystem_tool_runs_through_the_registry(
    settings: Settings, tmp_path
) -> None:
    """The whole path: registry -> MCP client -> server -> filesystem."""
    from contextlib import AsyncExitStack

    async with AsyncExitStack() as stack:
        sources = await MCPServerRegistry.from_settings(settings).open_sources(stack)
        registry = ToolRegistry(sources)
        await registry.refresh()

        result = await registry.call("detect_workspace", {"path": str(BACKEND_ROOT)})

    assert not result.is_error
    assert result.structured["success"] is True
    assert "python" in result.structured["project_types"]


async def test_run_command_arrives_with_its_approval_prompt(settings: Settings) -> None:
    """The server's prompt template survives discovery, so the user sees a
    sentence rather than a description written for the model."""
    from contextlib import AsyncExitStack

    from app.agent.approvals import describe

    async with AsyncExitStack() as stack:
        sources = await MCPServerRegistry.from_settings(settings).open_sources(stack)
        registry = ToolRegistry(sources)
        await registry.refresh()
        definition = registry.require("run_command")

    assert definition.prompt_template == "Run {command} in {working_directory}"
    prompt = describe(
        definition.name,
        definition.description,
        {"command": "pytest", "working_directory": "~/Projects/nexus"},
        definition.prompt_template,
    )
    assert prompt == "Run pytest in ~/Projects/nexus"


async def test_a_tool_without_a_template_still_reads_well(settings: Settings) -> None:
    from contextlib import AsyncExitStack

    from app.agent.approvals import describe

    async with AsyncExitStack() as stack:
        sources = await MCPServerRegistry.from_settings(settings).open_sources(stack)
        registry = ToolRegistry(sources)
        await registry.refresh()
        definition = registry.require("open_application")

    assert definition.prompt_template is None
    assert describe(
        definition.name, definition.description, {"application": "Safari"}, None
    ) == "Open an installed macOS application by name (application: Safari)"


async def test_a_dangerous_command_is_refused_through_the_registry(
    settings: Settings,
) -> None:
    """Refused by the MCP server's policy, before anything is executed."""
    from contextlib import AsyncExitStack

    async with AsyncExitStack() as stack:
        sources = await MCPServerRegistry.from_settings(settings).open_sources(stack)
        registry = ToolRegistry(sources)
        await registry.refresh()

        for command in ("rm -rf ~", "pytest && rm -rf /", "sudo reboot", "git push"):
            result = await registry.call(
                "run_command",
                {"command": command, "working_directory": str(BACKEND_ROOT)},
            )
            assert result.structured["success"] is False, command
            assert result.structured["status"] == "rejected", command
