"""Tool registry and permission classification."""

from __future__ import annotations

import pytest
from conftest import FakeToolSource, tool_definition

from app.core.errors import ToolError
from app.tools.permissions import (
    DEFAULT_PERMISSION_LEVEL,
    PermissionLevel,
    PermissionPolicy,
    classify,
)
from app.tools.registry import ToolRegistry, ToolResult


async def test_registry_discovers_tools_from_its_sources() -> None:
    source = FakeToolSource([tool_definition("battery_status"), tool_definition("system_info")])
    registry = ToolRegistry([source])

    await registry.refresh()

    assert [tool.name for tool in registry.list_tools()] == [
        "battery_status",
        "system_info",
    ]
    assert registry.require("system_info").source == "fake"


async def test_registry_executes_through_the_owning_source() -> None:
    source = FakeToolSource(
        [tool_definition("battery_status")],
        {"battery_status": ToolResult(content="87%", structured={"percentage": 87})},
    )
    registry = ToolRegistry([source])
    await registry.refresh()

    result = await registry.call("battery_status", {})

    assert result.content == "87%"
    assert result.structured == {"percentage": 87}
    assert source.calls == [("battery_status", {})]


async def test_unknown_tool_raises_tool_error() -> None:
    registry = ToolRegistry([FakeToolSource([])])
    await registry.refresh()

    with pytest.raises(ToolError, match="Unknown tool"):
        await registry.call("nope", {})


async def test_restricted_tools_are_not_offered_to_the_model() -> None:
    registry = ToolRegistry(
        [
            FakeToolSource(
                [
                    tool_definition("system_info", PermissionLevel.SAFE),
                    tool_definition("open_application", PermissionLevel.CONFIRM),
                    tool_definition("delete_file", PermissionLevel.RESTRICTED),
                ]
            )
        ]
    )
    await registry.refresh()

    offered = {spec.name for spec in registry.model_specs()}

    assert offered == {"system_info", "open_application"}


async def test_the_first_source_to_claim_a_name_wins() -> None:
    first = FakeToolSource([tool_definition("system_info", source="first")])
    second = FakeToolSource([tool_definition("system_info", source="second")])
    registry = ToolRegistry([first, second])

    await registry.refresh()

    assert registry.require("system_info").source == "first"


# --- permissions -----------------------------------------------------------


@pytest.mark.parametrize(
    ("tool", "expected"),
    [
        ("battery_status", PermissionLevel.SAFE),
        ("system_info", PermissionLevel.SAFE),
        ("open_application", PermissionLevel.CONFIRM),
        ("execute_command", PermissionLevel.CONFIRM),
        ("delete_file", PermissionLevel.RESTRICTED),
    ],
)
def test_spec_classification(tool: str, expected: PermissionLevel) -> None:
    assert classify(tool) == expected


def test_unknown_tools_are_restricted_by_default() -> None:
    assert DEFAULT_PERMISSION_LEVEL is PermissionLevel.RESTRICTED
    assert classify("something_nobody_classified") is PermissionLevel.RESTRICTED


def test_a_tool_may_declare_its_own_level() -> None:
    assert classify("brand_new_tool", "SAFE") is PermissionLevel.SAFE
    # A nonsense declaration falls back to the baseline instead of being trusted.
    assert classify("brand_new_tool", "totally-safe-honest") is PermissionLevel.RESTRICTED


def test_safe_tools_run_without_approval() -> None:
    decision = PermissionPolicy().evaluate("battery_status", PermissionLevel.SAFE)

    assert decision.allowed
    assert not decision.requires_confirmation


def test_confirm_tools_need_explicit_approval() -> None:
    policy = PermissionPolicy()

    decision = policy.evaluate("open_application", PermissionLevel.CONFIRM)

    assert not decision.allowed
    assert decision.requires_confirmation
    assert "approval" in decision.reason


def test_confirm_tools_run_once_approved() -> None:
    policy = PermissionPolicy(["open_application"])

    assert policy.evaluate("open_application", PermissionLevel.CONFIRM).allowed


def test_restricted_tools_are_never_allowed() -> None:
    policy = PermissionPolicy(["delete_file"])

    decision = policy.evaluate("delete_file", PermissionLevel.RESTRICTED)

    assert not decision.allowed
    assert not decision.requires_confirmation
