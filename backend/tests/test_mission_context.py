"""Context reaching the mission planner, and precedence over memory.

§17: objective -> ContextCollector -> memories/workspace/machine -> planner.
§10: a step's own fresh tool result always outranks what memory said.
"""

from __future__ import annotations

from conftest import StubProvider
from langchain_core.messages import AIMessage
from test_mission_engine import _FakeSource, build_runner, event_types, plan_call, tool, tool_turn

from app.agent.events import EventType
from app.agent.tasks import TaskStatus
from app.core.config import Settings
from app.mission.planner import PLANNER_TOOL_NAME
from app.tools.permissions import PermissionLevel
from app.tools.registry import ToolResult


async def test_memory_reaches_the_planners_prompt(settings: Settings) -> None:
    """The planner call's own system prompt must contain what memory knew."""
    source = _FakeSource(
        [
            tool("list_memories", PermissionLevel.SAFE),
            tool("git_status"),
        ],
        {
            "list_memories": ToolResult(
                content="", structured={
                    "success": True, "count": 1,
                    "memories": [
                        {"id": "mem_1", "type": "PROJECT", "key": "nexus",
                         "value": {"path": "~/Documents/nexus"}, "confidence": 1.0},
                    ],
                },
            ),
            "git_status": ToolResult(content="", structured={"success": True, "branch": "main", "clean": True}),
        },
    )
    provider = StubProvider(
        [
            plan_call([{"id": "step_1", "description": "Check status", "tool": "git_status"}]),
            tool_turn("git_status"),
            AIMessage(content="Clean."),
            AIMessage(content="All good."),
        ]
    )
    runner = build_runner(settings, provider, source)

    await runner.run("Check my NEXUS project status and verify it is clean.")

    planner_call = provider.calls[0]
    system_prompt = planner_call[0][0].content
    assert "nexus" in system_prompt.lower()
    assert "~/Documents/nexus" in system_prompt
    # The tool_choice really was forced onto the planner's pseudo-tool.
    assert planner_call[2] == PLANNER_TOOL_NAME


async def test_workspace_state_reaches_the_planners_prompt(settings: Settings) -> None:
    source = _FakeSource(
        [tool("detect_workspace")],
        {
            "detect_workspace": ToolResult(
                content="", structured={
                    "success": True, "path": "/x/nexus",
                    "project_types": ["python", "fastapi"], "is_git_repository": False,
                },
            ),
        },
    )
    provider = StubProvider(
        [plan_call([{"id": "step_1", "description": "Inspect", "tool": "detect_workspace"}])]
    )
    runner = build_runner(settings, provider, source)

    await runner.run("Inspect /x/nexus and check its Git status.")

    system_prompt = provider.calls[0][0][0].content
    assert "/x/nexus" in system_prompt
    assert "fastapi" in system_prompt


async def test_the_prompt_states_precedence_explicitly(settings: Settings) -> None:
    source = _FakeSource(
        [tool("list_memories", PermissionLevel.SAFE)],
        {"list_memories": ToolResult(
            content="", structured={"success": True, "count": 1, "memories": [
                {"id": "m", "type": "FACT", "key": "x", "value": {"a": 1}, "confidence": 1.0}
            ]},
        )},
    )
    provider = StubProvider(
        [plan_call([{"id": "step_1", "description": "x", "tool": "list_memories"}])]
    )
    runner = build_runner(settings, provider, source)

    await runner.run("Check x and then list it again.")

    system_prompt = provider.calls[0][0][0].content
    assert "outranks" in system_prompt.lower()


# --- precedence: current tool result beats memory, in practice -------------


async def test_a_fresh_tool_result_overwrites_a_stale_memory_in_later_steps(
    settings: Settings,
) -> None:
    """Memory claims one port; the mission's own step discovers another.
    The later step must be told the fresh one, not the remembered one."""
    source = _FakeSource(
        [
            tool("list_memories", PermissionLevel.SAFE),
            tool("start_process", PermissionLevel.CONFIRM, properties={"command": {}}),
            tool("check_local_service", properties={"url": {}}),
        ],
        {
            "list_memories": ToolResult(
                content="", structured={"success": True, "count": 1, "memories": [
                    {"id": "m", "type": "WORKSPACE", "key": "backend",
                     "value": {"path": "/x/backend", "url": "http://127.0.0.1:8000"},
                     "confidence": 1.0},
                ]},
            ),
            "start_process": ToolResult(
                content="", structured={"success": True, "url": "http://127.0.0.1:9999"}
            ),
            "check_local_service": ToolResult(content="", structured={"success": True, "reachable": True}),
        },
    )
    provider = StubProvider(
        [
            plan_call(
                [
                    {"id": "step_1", "description": "Start backend", "tool": "start_process"},
                    {"id": "step_2", "description": "Check health", "tool": "check_local_service",
                     "depends_on": ["step_1"]},
                ]
            ),
            tool_turn("start_process", {"command": "uv run uvicorn app.main:app"}),
            AIMessage(content="Started on 9999."),
            tool_turn("check_local_service", {"url": "http://127.0.0.1:9999"}),
            AIMessage(content="Healthy."),
            AIMessage(content="Backend started and healthy."),
        ]
    )
    import asyncio

    from app.agent.approvals import ApprovalBroker

    broker = ApprovalBroker()
    runner = build_runner(settings, provider, source, broker=broker)

    record = runner.start("Start my backend and check whether it is healthy.")
    async with asyncio.timeout(3):
        while not broker.list_pending():
            await asyncio.sleep(0.01)
    broker.approve(broker.list_pending()[0].request_id)
    await runner.task_store._runs[record.task_id]

    assert record.status is TaskStatus.COMPLETED
    # Step 2's instruction must carry the FRESH url from step 1's own result —
    # the remembered one (port 8000) must not be what it was told to check.
    step_2_instruction = provider.calls[3][0][-1].content
    assert "http://127.0.0.1:9999" in step_2_instruction
    assert "8000" not in step_2_instruction


async def test_memory_seeds_context_but_a_fresh_result_wins_immediately(
    settings: Settings,
) -> None:
    """Even the *first* step, if it discovers something itself, must not be
    contradicted by a memory-seeded value for a later step in the same run."""
    source = _FakeSource(
        [
            tool("list_memories", PermissionLevel.SAFE),
            tool("detect_workspace"),
            tool("git_status"),
        ],
        {
            "list_memories": ToolResult(
                content="", structured={"success": True, "count": 1, "memories": [
                    {"id": "m", "type": "PROJECT", "key": "nexus",
                     "value": {"path": "/remembered/stale/path"}, "confidence": 1.0},
                ]},
            ),
            "detect_workspace": ToolResult(
                content="", structured={"success": True, "path": "/current/real/path",
                                          "project_types": ["python"], "is_git_repository": True},
            ),
            "git_status": ToolResult(content="", structured={"success": True, "branch": "main", "clean": True}),
        },
    )
    provider = StubProvider(
        [
            plan_call(
                [
                    {"id": "step_1", "description": "Inspect", "tool": "detect_workspace"},
                    {"id": "step_2", "description": "Git status", "tool": "git_status",
                     "depends_on": ["step_1"]},
                ]
            ),
            tool_turn("detect_workspace"),
            AIMessage(content="Found it."),
            tool_turn("git_status"),
            AIMessage(content="Clean."),
            AIMessage(content="All set."),
        ]
    )
    runner = build_runner(settings, provider, source)

    await runner.run("Prepare the nexus project for development.")

    step_2_instruction = provider.calls[3][0][-1].content
    assert "/current/real/path" in step_2_instruction
    assert "/remembered/stale/path" not in step_2_instruction
