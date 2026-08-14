"""Memory tools through the ordinary chat agent: proposal, approval, outcome.

save_memory and delete_memory are CONFIRM tools like any other — this proves
they go through the *same* approval broker (no second permission system) and
that the memory-aware narration (memory_proposed/memory_saved/memory_deleted)
rides the existing event pipeline correctly.
"""

from __future__ import annotations

import asyncio

from conftest import FakeToolSource, StubProvider, tool_definition
from langchain_core.messages import AIMessage

from app.agent.approvals import ApprovalBroker
from app.agent.events import EventType
from app.agent.runner import AgentRunner
from app.agent.tasks import TaskStatus, TaskStore
from app.core.config import Settings
from app.models.router import ModelRouter
from app.tools.permissions import PermissionLevel
from app.tools.registry import ToolResult


class _SourceRegistry:
    def __init__(self, source: FakeToolSource) -> None:
        self._source = source

    async def open_sources(self, _stack) -> list:
        return [self._source]


async def _await_pending(broker: ApprovalBroker, timeout: float = 3.0):
    async with asyncio.timeout(timeout):
        while not broker.list_pending():
            await asyncio.sleep(0.01)
    return broker.list_pending()[0]


def build_runner(settings: Settings, provider: StubProvider, source, broker=None) -> AgentRunner:
    return AgentRunner(
        settings=settings,
        router=ModelRouter(settings, {"groq": lambda _s: provider}),
        task_store=TaskStore(),
        server_registry=_SourceRegistry(source),
        broker=broker or ApprovalBroker(),
        pool=None,
    )


def event_types(record) -> list[str]:
    return [str(e.type) for e in record.events]


# --- save: propose, approve, narrate ----------------------------------


async def test_saving_a_memory_is_proposed_then_approved(settings: Settings) -> None:
    source = FakeToolSource(
        [tool_definition("save_memory", PermissionLevel.CONFIRM)],
        {"save_memory": ToolResult(
            content="", structured={"success": True, "memory": {"id": "mem_1", "key": "nexus_project"}}
        )},
    )
    provider = StubProvider(
        [
            AIMessage(
                content="", tool_calls=[{
                    "name": "save_memory",
                    "args": {"type": "PROJECT", "key": "nexus_project", "value": {"path": "~/Documents/nexus"}},
                    "id": "c1", "type": "tool_call",
                }],
            ),
            AIMessage(content="Remembered your NEXUS project."),
        ]
    )
    broker = ApprovalBroker()
    runner = build_runner(settings, provider, source, broker=broker)

    record = runner.start("Remember that my main NEXUS project is in ~/Documents/nexus.")
    request = await _await_pending(broker)

    # memory_proposed appears before approval, describing the actual save.
    proposed = [e for e in record.events if e.type is EventType.MEMORY_PROPOSED]
    assert len(proposed) == 1
    assert "nexus_project" in proposed[0].message
    assert "~/Documents/nexus" in proposed[0].message
    assert proposed[0].data["request_id"] == request.request_id

    broker.approve(request.request_id)
    await runner.task_store._runs[record.task_id]

    assert record.status is TaskStatus.COMPLETED
    saved = [e for e in record.events if e.type is EventType.MEMORY_SAVED]
    assert len(saved) == 1
    assert saved[0].data["memory_id"] == "mem_1"
    assert saved[0].data["key"] == "nexus_project"


async def test_a_denied_save_is_not_narrated_as_saved(settings: Settings) -> None:
    source = FakeToolSource([tool_definition("save_memory", PermissionLevel.CONFIRM)])
    provider = StubProvider(
        [
            AIMessage(
                content="", tool_calls=[{
                    "name": "save_memory",
                    "args": {"type": "FACT", "key": "x", "value": {"a": 1}},
                    "id": "c1", "type": "tool_call",
                }],
            ),
            AIMessage(content="I did not remember that, since you declined."),
        ]
    )
    broker = ApprovalBroker()
    runner = build_runner(settings, provider, source, broker=broker)

    record = runner.start("Remember that x is 1.")
    request = await _await_pending(broker)
    broker.deny(request.request_id)
    await runner.task_store._runs[record.task_id]

    assert event_types(record).count(EventType.MEMORY_SAVED) == 0
    assert source.calls == []


# --- delete: forget everything requires confirmation -----------------------


async def test_forgetting_everything_about_a_project_is_proposed_then_deleted(
    settings: Settings,
) -> None:
    source = FakeToolSource(
        [tool_definition("delete_memory", PermissionLevel.CONFIRM)],
        {"delete_memory": ToolResult(
            content="", structured={"success": True, "count": 2, "deleted_keys": ["nexus_backend", "nexus_frontend"]}
        )},
    )
    provider = StubProvider(
        [
            AIMessage(
                content="", tool_calls=[{
                    "name": "delete_memory", "args": {"key_contains": "nexus"},
                    "id": "c1", "type": "tool_call",
                }],
            ),
            AIMessage(content="Forgot everything about NEXUS."),
        ]
    )
    broker = ApprovalBroker()
    runner = build_runner(settings, provider, source, broker=broker)

    record = runner.start("Forget everything you know about NEXUS.")
    request = await _await_pending(broker)

    proposed = [e for e in record.events if e.type is EventType.MEMORY_PROPOSED][0]
    assert "nexus" in proposed.message.lower()

    broker.approve(request.request_id)
    await runner.task_store._runs[record.task_id]

    deleted = [e for e in record.events if e.type is EventType.MEMORY_DELETED][0]
    assert deleted.data["count"] == 2


async def test_wipe_all_is_proposed_distinctly(settings: Settings) -> None:
    source = FakeToolSource([tool_definition("delete_memory", PermissionLevel.CONFIRM)])
    provider = StubProvider(
        [
            AIMessage(
                content="", tool_calls=[{
                    "name": "delete_memory", "args": {"wipe_all": True}, "id": "c1", "type": "tool_call",
                }],
            ),
        ]
    )
    broker = ApprovalBroker()
    runner = build_runner(settings, provider, source, broker=broker)

    record = runner.start("Delete every single memory you have, no matter what.")
    request = await _await_pending(broker)

    proposed = [e for e in record.events if e.type is EventType.MEMORY_PROPOSED][0]
    assert "permanently" in proposed.message.lower()

    broker.deny(request.request_id)  # never actually confirmed in this test
    await runner.task_store._runs[record.task_id]

    assert source.calls == []


# --- SAFE memory reads never need approval ----------------------------


async def test_listing_memories_never_asks_for_approval(settings: Settings) -> None:
    source = FakeToolSource(
        [tool_definition("list_memories", PermissionLevel.SAFE)],
        {"list_memories": ToolResult(
            content="", structured={"success": True, "count": 1, "memories": [
                {"id": "mem_1", "type": "PROJECT", "key": "nexus", "value": {"path": "~/nexus"}, "confidence": 1.0}
            ]}
        )},
    )
    provider = StubProvider(
        [
            AIMessage(
                content="", tool_calls=[{"name": "list_memories", "args": {}, "id": "c1", "type": "tool_call"}]
            ),
            AIMessage(content="You have one saved project: NEXUS."),
        ]
    )
    broker = ApprovalBroker()
    runner = build_runner(settings, provider, source, broker=broker)

    record = await runner.run("What do you remember about my projects?")

    assert record.status is TaskStatus.COMPLETED
    assert broker.list_pending() == []
    assert EventType.PERMISSION_REQUIRED not in event_types(record)
