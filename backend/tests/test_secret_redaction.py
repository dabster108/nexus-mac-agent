"""Secrets must not reach the log, however they enter the system.

A tool argument can hold a token, a file's contents or a command line. The
logging layer therefore records argument *names* and never their values; these
tests pin that down at the two places arguments are logged, so a future
`logger.info("... %s", arguments)` fails here rather than in production.
"""

from __future__ import annotations

import logging

import pytest
from conftest import FakeToolSource, StubProvider, tool_definition
from langchain_core.messages import AIMessage

from app.agent.graph import build_agent_graph
from app.agent.state import initial_state
from app.core.logging import safe_keys
from app.tools.permissions import PermissionPolicy
from app.tools.registry import ToolRegistry, ToolResult

SECRET = "ghp_aBcD1234567890EfGhIjKlMnOpQrStUvWx"


def tool_call(name: str, args: dict, call_id: str = "call_1") -> dict:
    return {"name": name, "args": args, "id": call_id, "type": "tool_call"}


def test_safe_keys_keeps_names_and_drops_values() -> None:
    assert safe_keys({"token": SECRET, "path": "/tmp/x"}) == ["path", "token"]
    assert safe_keys({}) == []
    assert safe_keys(None) == []


async def test_a_secret_in_a_tool_argument_never_reaches_the_log(
    caplog: pytest.LogCaptureFixture,
) -> None:
    source = FakeToolSource(
        [tool_definition("save_memory")],
        {"save_memory": ToolResult(content="ok", structured=None)},
    )
    provider = StubProvider(
        [
            AIMessage(
                content="",
                tool_calls=[tool_call("save_memory", {"key": "gh", "token": SECRET})],
            ),
            AIMessage(content="Saved."),
        ]
    )
    registry = ToolRegistry([source])
    await registry.refresh()
    graph = build_agent_graph(
        provider=provider,
        registry=registry,
        # Pre-approved so the call actually executes and is logged.
        policy=PermissionPolicy(["save_memory"]),
    )

    with caplog.at_level(logging.DEBUG):
        await graph.ainvoke(initial_state("task_secret", "remember my token"))

    combined = "\n".join(record.getMessage() for record in caplog.records)
    assert SECRET not in combined
    # The argument's *name* is what makes the log useful for debugging.
    assert "token" in combined


async def test_a_secret_in_a_tool_result_never_reaches_the_log(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Results are handed to the model, but only ever summarised into the log."""
    source = FakeToolSource(
        [tool_definition("read_file")],
        {"read_file": ToolResult(content=f"API_KEY={SECRET}", structured=None)},
    )
    provider = StubProvider(
        [
            AIMessage(content="", tool_calls=[tool_call("read_file", {"path": "/tmp/a"})]),
            AIMessage(content="Read it."),
        ]
    )
    registry = ToolRegistry([source])
    await registry.refresh()
    graph = build_agent_graph(
        provider=provider, registry=registry, policy=PermissionPolicy()
    )

    with caplog.at_level(logging.DEBUG):
        await graph.ainvoke(initial_state("task_secret2", "read it"))

    combined = "\n".join(record.getMessage() for record in caplog.records)
    assert SECRET not in combined
