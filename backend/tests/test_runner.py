"""End-to-end runner: FastAPI -> LangGraph -> MCP -> tool -> result.

The model is stubbed (no network, no API key); everything below it is real.
"""

from __future__ import annotations

import asyncio
from collections.abc import Sequence

import pytest
from conftest import StubProvider
from langchain_core.messages import AIMessage, BaseMessage

from app.agent.events import EventType
from app.agent.runner import AgentRunner
from app.agent.tasks import TaskNotFound, TaskStatus, TaskStore
from app.core.config import Settings
from app.mcp.registry import MCPServerRegistry
from app.models.base import ToolSpec
from app.models.router import ModelRouter


class SlowProvider(StubProvider):
    """Takes its time, so a run can be observed mid-flight."""

    def __init__(self, responses: Sequence[AIMessage], delay: float) -> None:
        super().__init__(responses)
        self._delay = delay

    async def ainvoke(
        self, messages: Sequence[BaseMessage], tools: Sequence[ToolSpec] = ()
    ) -> AIMessage:
        await asyncio.sleep(self._delay)
        return await super().ainvoke(messages, tools)


def build_runner(settings: Settings, provider: StubProvider) -> AgentRunner:
    router = ModelRouter(settings, {"groq": lambda _s: provider})
    return AgentRunner(
        settings=settings,
        router=router,
        task_store=TaskStore(),
        server_registry=MCPServerRegistry.from_settings(settings),
    )


async def test_a_full_run_calls_a_real_mcp_tool(settings: Settings) -> None:
    provider = StubProvider(
        [
            AIMessage(
                content="",
                tool_calls=[
                    {"name": "system_info", "args": {}, "id": "c1", "type": "tool_call"}
                ],
            ),
            AIMessage(content="You are running macOS on Apple silicon."),
        ]
    )
    runner = build_runner(settings, provider)

    record = await runner.run("what mac am i on?")

    assert record.status is TaskStatus.COMPLETED
    assert record.response == "You are running macOS on Apple silicon."
    assert record.task_id.startswith("task_")

    types = [str(event.type) for event in record.events]
    # Phase 10 gathers context before the model runs, so the run now opens with
    # context events. The execution sequence itself is unchanged.
    assert types[0] == EventType.TASK_STARTED
    assert [t for t in types if not t.startswith(("memory_", "context_", "workspace_"))] == [
        EventType.TASK_STARTED,
        EventType.TOOL_REQUESTED,
        EventType.TOOL_STARTED,
        EventType.TOOL_COMPLETED,
        EventType.AGENT_MESSAGE,
        EventType.TASK_COMPLETED,
    ]

    # The tool result really came from the MCP server.
    tool_message = provider.calls[-1][0][-1]
    assert "architecture" in tool_message.content


async def test_the_task_is_retrievable_afterwards(settings: Settings) -> None:
    runner = build_runner(settings, StubProvider([AIMessage(content="Hi.")]))

    record = await runner.run("hello")

    assert runner.task_store.get(record.task_id) is record


async def test_an_empty_message_is_rejected_before_anything_runs(
    settings: Settings,
) -> None:
    import pytest

    from app.core.errors import ValidationError

    runner = build_runner(settings, StubProvider([]))

    with pytest.raises(ValidationError):
        await runner.run("   ")


async def test_a_model_failure_produces_a_clean_task_record(settings: Settings) -> None:
    class Boom(StubProvider):
        async def ainvoke(self, messages, tools=()):  # type: ignore[no-untyped-def]
            raise RuntimeError("groq exploded: key sk-secret-123")

    runner = build_runner(settings, Boom([]))

    record = await runner.run("what is my battery?")

    assert record.status is TaskStatus.ERROR
    assert record.error is not None
    # The vendor's message (which could contain anything) never reaches the client.
    assert "sk-secret-123" not in str(record.to_dict())
    assert str(record.events[-1].type) == EventType.TASK_ERROR


async def test_start_returns_before_the_agent_finishes(settings: Settings) -> None:
    provider = SlowProvider([AIMessage(content="Done.")], delay=0.2)
    runner = build_runner(settings, provider)

    record = runner.start("hello")

    # Accepted, not finished.
    assert record.status is TaskStatus.RUNNING
    assert runner.task_store.is_running(record.task_id)

    await runner.task_store._runs[record.task_id]

    assert record.status is TaskStatus.COMPLETED
    assert record.response == "Done."
    assert record.completed_at is not None


async def test_cancelling_a_running_task_stops_it(settings: Settings) -> None:
    provider = SlowProvider([AIMessage(content="Never gets here.")], delay=5.0)
    runner = build_runner(settings, provider)
    record = runner.start("something slow")
    await asyncio.sleep(0.05)  # let the run reach the model call

    cancelled = await runner.cancel(record.task_id)

    assert cancelled.status is TaskStatus.CANCELLED
    assert cancelled.completed_at is not None
    assert str(record.events[-1].type) == EventType.TASK_CANCELLED
    assert not runner.task_store.is_running(record.task_id)


async def test_cancelling_a_finished_task_leaves_it_alone(settings: Settings) -> None:
    runner = build_runner(settings, StubProvider([AIMessage(content="Done.")]))
    record = await runner.run("hello")

    result = await runner.cancel(record.task_id)

    assert result.status is TaskStatus.COMPLETED
    assert EventType.TASK_CANCELLED not in [str(event.type) for event in result.events]


async def test_cancelling_an_unknown_task_raises(settings: Settings) -> None:
    runner = build_runner(settings, StubProvider([]))

    with pytest.raises(TaskNotFound):
        await runner.cancel("task_nope")


async def test_the_runner_lists_the_live_tools(settings: Settings) -> None:
    runner = build_runner(settings, StubProvider([]))

    tools = {tool.name: tool for tool in await runner.list_tools()}

    assert "battery_status" in tools
    assert str(tools["battery_status"].permission) == "SAFE"
