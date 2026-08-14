"""Shared test fixtures.

Tests never touch the network: the model provider is stubbed and the tool layer
is exercised either through a fake source or the bundled local MCP server.
"""

from __future__ import annotations

import sys
from collections.abc import Iterator, Sequence
from typing import Any

import pytest
from langchain_core.messages import AIMessage, BaseMessage

from app.agent.approvals import ApprovalBroker, get_approval_broker
from app.agent.runner import get_agent_runner
from app.agent.tasks import get_task_store
from app.core.config import Settings
from app.models.base import ModelProvider, ToolSpec
from app.tools.permissions import PermissionLevel
from app.tools.registry import ToolDefinition, ToolResult


class StubProvider(ModelProvider):
    """Replays a scripted sequence of assistant turns."""

    name = "stub"

    def __init__(self, responses: Sequence[AIMessage]) -> None:
        self._responses = list(responses)
        self.calls: list[tuple[list[BaseMessage], list[ToolSpec], str | None]] = []

    @property
    def model(self) -> str:
        return "stub-model"

    async def ainvoke(
        self,
        messages: Sequence[BaseMessage],
        tools: Sequence[ToolSpec] = (),
        *,
        tool_choice: str | None = None,
    ) -> AIMessage:
        self.calls.append((list(messages), list(tools), tool_choice))
        if not self._responses:
            return AIMessage(content="(no scripted response)")
        return self._responses.pop(0)


class FakeToolSource:
    """An in-process tool source, standing in for an MCP server."""

    def __init__(
        self,
        definitions: Sequence[ToolDefinition],
        results: dict[str, ToolResult] | None = None,
    ) -> None:
        self._definitions = list(definitions)
        self._results = results or {}
        self.calls: list[tuple[str, dict[str, Any]]] = []

    @property
    def name(self) -> str:
        return "fake"

    async def list_tools(self) -> Sequence[ToolDefinition]:
        return self._definitions

    async def call_tool(self, name: str, arguments: dict[str, Any]) -> ToolResult:
        self.calls.append((name, arguments))
        return self._results.get(name, ToolResult(content=f"{name} ok"))


def tool_definition(
    name: str,
    permission: PermissionLevel = PermissionLevel.SAFE,
    source: str = "fake",
) -> ToolDefinition:
    return ToolDefinition(
        name=name,
        description=f"Test tool {name}",
        input_schema={"type": "object", "properties": {}},
        source=source,
        permission=permission,
    )


@pytest.fixture
def settings() -> Settings:
    """Settings that never reach a real provider."""
    return Settings(
        groq_api_key="test-groq-key",
        mistral_api_key="test-mistral-key",
        default_model_provider="groq",
        groq_model="test-groq-model",
        mistral_model="test-mistral-model",
        model_temperature=0.0,
        backend_host="127.0.0.1",
        backend_port=8000,
        cors_origins=("http://localhost:3000",),
        agent_max_iterations=3,
        request_timeout_seconds=10.0,
        permission_timeout_seconds=2.0,
        mission_max_steps=10,
        mission_max_retries_per_step=2,
        mission_max_tool_calls=30,
        mission_max_runtime_seconds=30.0,
        context_max_memories=10,
        context_max_workspace_facts=20,
        context_max_chars=4000,
        mcp_server_command=sys.executable,
        mcp_server_args=("-m", "nexus_mac_mcp"),
        log_level="WARNING",
    )


@pytest.fixture(autouse=True)
def reset_runtime_state() -> Iterator[None]:
    """Give every test a fresh task store, approval broker and runner.

    These are process-wide singletons in production; sharing them across tests
    would let one test's pending permission leak into the next.
    """
    for factory in (get_task_store, get_approval_broker, get_agent_runner):
        factory.cache_clear()
    yield
    for factory in (get_task_store, get_approval_broker, get_agent_runner):
        factory.cache_clear()


@pytest.fixture
def broker() -> ApprovalBroker:
    return get_approval_broker()
