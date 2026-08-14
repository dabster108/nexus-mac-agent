"""The mission engine: execution, dependencies, approval, retries, safety limits.

Runs through the real public entry point (``AgentRunner.run``/``.start``) so
these exercise exactly what production does — mission detection, planning,
per-step task creation, event mirroring, and reuse of ``_sink_for``/
``_finalise`` — with a fake tool registry standing in for MCP.
"""

from __future__ import annotations

import asyncio

from conftest import StubProvider
from langchain_core.messages import AIMessage

from app.agent.approvals import ApprovalBroker
from app.agent.events import EventType
from app.agent.runner import AgentRunner
from app.agent.tasks import TaskStatus, TaskStore
from app.core.config import Settings
from app.mission.engine import MissionEngine, MissionLimits, _mission_outcome, _run_if_eligible
from app.mission.planner import PLANNER_TOOL_NAME
from app.mission.state import Mission, MissionStatus, MissionStep, StepStatus
from app.mission.store import InMemoryMissionStore
from app.models.router import ModelRouter
from app.tools.permissions import PermissionLevel
from app.tools.registry import ToolDefinition, ToolResult


class _FakeSource:
    def __init__(self, definitions, results=None):
        self._definitions = list(definitions)
        self._results = results or {}
        self.calls: list[tuple[str, dict]] = []

    @property
    def name(self):
        return "fake"

    async def list_tools(self):
        return self._definitions

    async def call_tool(self, name, arguments):
        self.calls.append((name, arguments))
        outcome = self._results.get(name)
        if callable(outcome):
            return outcome(arguments)
        return outcome or ToolResult(content=f"{name} ok")


class _SourceRegistry:
    def __init__(self, *sources):
        self._sources = sources

    async def open_sources(self, _stack):
        return list(self._sources)


def tool(name: str, permission=PermissionLevel.SAFE, properties=None) -> ToolDefinition:
    return ToolDefinition(
        name=name,
        description=f"Test tool {name}",
        input_schema={"type": "object", "properties": properties or {}},
        source="fake",
        permission=permission,
    )


def plan_call(steps: list[dict], objective: str = "Do the thing.") -> AIMessage:
    return AIMessage(
        content="",
        tool_calls=[
            {
                "name": PLANNER_TOOL_NAME,
                "args": {"objective": objective, "steps": steps},
                "id": "plan_call",
                "type": "tool_call",
            }
        ],
    )


def tool_turn(tool_name: str, args: dict | None = None, call_id: str = "c1") -> AIMessage:
    return AIMessage(
        content="",
        tool_calls=[{"name": tool_name, "args": args or {}, "id": call_id, "type": "tool_call"}],
    )


def build_runner(settings: Settings, provider: StubProvider, *sources, broker=None) -> AgentRunner:
    router = ModelRouter(settings, {"groq": lambda _s: provider})
    return AgentRunner(
        settings=settings,
        router=router,
        task_store=TaskStore(),
        server_registry=_SourceRegistry(*sources),
        broker=broker or ApprovalBroker(),
        pool=None,
        mission_store=InMemoryMissionStore(),
    )


def event_types(record) -> list[str]:
    return [str(e.type) for e in record.events]


async def _await_pending(broker: ApprovalBroker, timeout: float = 3.0):
    async with asyncio.timeout(timeout):
        while not broker.list_pending():
            await asyncio.sleep(0.01)
    return broker.list_pending()[0]


# --- a single-step mission runs end to end ---------------------------------


async def test_a_single_safe_step_mission(settings: Settings) -> None:
    source = _FakeSource(
        [tool("detect_workspace")],
        {"detect_workspace": ToolResult(content="python project", structured={"path": "/x"})},
    )
    provider = StubProvider(
        [
            plan_call(
                [{"id": "step_1", "description": "Inspect the project", "tool": "detect_workspace"}],
                objective="Inspect",
            ),
            tool_turn("detect_workspace"),
            AIMessage(content="It's a Python project."),
            AIMessage(content="Your project is a Python project."),  # mission wrap-up
        ]
    )
    runner = build_runner(settings, provider, source)

    record = await runner.run("Prepare my project for development.")

    assert record.status is TaskStatus.COMPLETED
    assert record.response == "Your project is a Python project."
    assert source.calls == [("detect_workspace", {})]

    types = event_types(record)
    assert types == [
        EventType.TASK_STARTED,
        EventType.MISSION_STARTED,
        EventType.CONTEXT_COLLECTED,
        EventType.MISSION_PLAN_CREATED,
        EventType.MISSION_STEP_STARTED,
        EventType.TOOL_REQUESTED,
        EventType.TOOL_STARTED,
        EventType.TOOL_COMPLETED,
        EventType.AGENT_MESSAGE,  # the step's own conclusion, mirrored
        EventType.MISSION_STEP_COMPLETED,
        EventType.MISSION_COMPLETED,
        EventType.TASK_COMPLETED,  # the outer task's own completion
    ]

    # The step ran as a real, independently-inspectable task.
    started = next(e for e in record.events if e.type is EventType.MISSION_STARTED)
    step_started = next(e for e in record.events if e.type is EventType.MISSION_STEP_STARTED)
    assert started.data["mission_id"] and step_started.data["step_id"]
    assert step_started.data["mission_id"] == started.data["mission_id"]


async def test_the_step_ran_as_its_own_inspectable_task(settings: Settings) -> None:
    source = _FakeSource(
        [tool("battery_status")], {"battery_status": ToolResult(content="87%")}
    )
    provider = StubProvider(
        [
            plan_call([{"id": "step_1", "description": "Check battery", "tool": "battery_status"}]),
            tool_turn("battery_status"),
            AIMessage(content="87 percent."),
            AIMessage(content="Battery is at 87 percent."),
        ]
    )
    runner = build_runner(settings, provider, source)

    record = await runner.run("Prepare my project for development.")

    mission_step_started = [
        e for e in record.events if e.type is EventType.MISSION_STEP_STARTED
    ][0]
    step_task_id = None
    for step in runner.task_store.list_tasks():
        if step.task_id != record.task_id:
            step_task_id = step.task_id
    assert step_task_id is not None
    step_record = runner.task_store.get(step_task_id)
    assert step_record is not None
    assert step_record.status is TaskStatus.COMPLETED
    assert step_record.response == "87 percent."
    assert event_types(step_record) == [
        EventType.TASK_STARTED,
        EventType.TOOL_REQUESTED,
        EventType.TOOL_STARTED,
        EventType.TOOL_COMPLETED,
        EventType.AGENT_MESSAGE,
        EventType.TASK_COMPLETED,
    ]


# --- dependencies and run_if -----------------------------------------------


async def test_a_step_waits_for_its_dependency(settings: Settings) -> None:
    source = _FakeSource(
        [tool("detect_workspace"), tool("git_status")],
        {
            "detect_workspace": ToolResult(content="ok", structured={"path": "/x"}),
            "git_status": ToolResult(content="clean"),
        },
    )
    provider = StubProvider(
        [
            plan_call(
                [
                    {"id": "step_1", "description": "Inspect", "tool": "detect_workspace"},
                    {
                        "id": "step_2", "description": "Git status", "tool": "git_status",
                        "depends_on": ["step_1"],
                    },
                ]
            ),
            tool_turn("detect_workspace"),
            AIMessage(content="Inspected."),
            tool_turn("git_status"),
            AIMessage(content="Clean."),
            AIMessage(content="All good."),
        ]
    )
    runner = build_runner(settings, provider, source)

    record = await runner.run("Prepare my project for development.")

    assert record.status is TaskStatus.COMPLETED
    assert source.calls == [("detect_workspace", {}), ("git_status", {})]


async def test_on_success_step_is_skipped_after_a_failure(settings: Settings) -> None:
    """A step gated on success never runs once its dependency fails."""
    source = _FakeSource(
        [tool("run_command", properties={"command": {}}), tool("start_process")],
        {"run_command": ToolResult(content="boom", is_error=True)},
    )
    provider = StubProvider(
        [
            plan_call(
                [
                    {"id": "step_1", "description": "Run tests", "tool": "run_command"},
                    {
                        "id": "step_2", "description": "Start backend", "tool": "start_process",
                        "depends_on": ["step_1"], "run_if": "on_success",
                    },
                ]
            ),
            tool_turn("run_command", {"command": "pytest"}),
            AIMessage(content="Tests could not run."),
            AIMessage(content="Tests failed; backend not started."),
        ]
    )
    runner = build_runner(settings, provider, source)
    runner._settings = _with(runner._settings, mission_max_retries_per_step=0)

    record = await runner.run("Prepare my project for development.")

    assert source.calls == [("run_command", {"command": "pytest"})]
    skipped = [e for e in record.events if e.type is EventType.MISSION_STEP_SKIPPED]
    assert len(skipped) == 1
    assert skipped[0].data["step_id"] == "step_2"


async def test_on_failure_step_runs_only_after_a_failure(settings: Settings) -> None:
    """A diagnostic step that only makes sense after something went wrong."""
    source = _FakeSource(
        [tool("run_command", properties={"command": {}}), tool("process_logs")],
        {"run_command": ToolResult(content="boom", is_error=True)},
    )
    provider = StubProvider(
        [
            plan_call(
                [
                    {"id": "step_1", "description": "Run tests", "tool": "run_command"},
                    {
                        "id": "step_2", "description": "Inspect logs", "tool": "process_logs",
                        "depends_on": ["step_1"], "run_if": "on_failure",
                    },
                ]
            ),
            tool_turn("run_command", {"command": "pytest"}),
            AIMessage(content="Failed."),
            tool_turn("process_logs"),
            AIMessage(content="Logs show an import error."),
            AIMessage(content="Tests failed with an import error."),
        ]
    )
    runner = build_runner(settings, provider, source)
    runner._settings = _with(runner._settings, mission_max_retries_per_step=0)

    record = await runner.run("Prepare my project for development.")

    assert [c[0] for c in source.calls] == ["run_command", "process_logs"]
    # Diagnosed: the on_failure step completed, so the mission is not FAILED.
    assert record.status is TaskStatus.COMPLETED


async def test_a_failure_with_no_recovery_step_fails_the_mission(settings: Settings) -> None:
    source = _FakeSource(
        [tool("run_command", properties={"command": {}})],
        {"run_command": ToolResult(content="boom", is_error=True)},
    )
    provider = StubProvider(
        [
            plan_call([{"id": "step_1", "description": "Run tests", "tool": "run_command"}]),
            tool_turn("run_command", {"command": "pytest"}),
            AIMessage(content="Failed."),
        ]
    )
    runner = build_runner(settings, provider, source)
    runner._settings = _with(runner._settings, mission_max_retries_per_step=0)

    record = await runner.run("Prepare my project for development.")

    assert record.status is TaskStatus.ERROR
    assert EventType.MISSION_FAILED in event_types(record)


# --- permission: SAFE never asks, CONFIRM does ------------------------------


async def test_safe_steps_never_create_an_approval_request(settings: Settings) -> None:
    source = _FakeSource([tool("git_status")], {"git_status": ToolResult(content="clean")})
    provider = StubProvider(
        [
            plan_call([{"id": "step_1", "description": "Status", "tool": "git_status"}]),
            tool_turn("git_status"),
            AIMessage(content="Clean."),
            AIMessage(content="Repo is clean."),
        ]
    )
    broker = ApprovalBroker()
    runner = build_runner(settings, provider, source, broker=broker)

    record = await runner.run("Prepare my project for development.")

    assert record.status is TaskStatus.COMPLETED
    assert broker.list_pending() == []
    assert EventType.PERMISSION_REQUIRED not in event_types(record)


async def test_a_confirm_step_pauses_for_approval_then_resumes(settings: Settings) -> None:
    source = _FakeSource(
        [tool("start_process", PermissionLevel.CONFIRM, properties={"command": {}})],
        {"start_process": ToolResult(content="running", structured={"url": "http://127.0.0.1:8123"})},
    )
    provider = StubProvider(
        [
            plan_call([{"id": "step_1", "description": "Start backend", "tool": "start_process"}]),
            tool_turn("start_process", {"command": "uv run uvicorn app.main:app"}),
            AIMessage(content="Started the backend."),
            AIMessage(content="The backend is running."),
        ]
    )
    broker = ApprovalBroker()
    runner = build_runner(settings, provider, source, broker=broker)

    record = runner.start("Start my backend and check whether it is healthy.")
    request = await _await_pending(broker)

    assert request.tool == "start_process"
    assert source.calls == []  # not run while waiting
    for _ in range(50):
        if record.status is TaskStatus.PERMISSION_REQUIRED:
            break
        await asyncio.sleep(0.01)
    assert record.status is TaskStatus.PERMISSION_REQUIRED
    assert EventType.MISSION_WAITING_APPROVAL in event_types(record)

    broker.approve(request.request_id)
    await runner.task_store._runs[record.task_id]

    assert record.status is TaskStatus.COMPLETED
    assert source.calls == [("start_process", {"command": "uv run uvicorn app.main:app"})]


async def test_a_denied_confirm_step_fails_without_retry(settings: Settings) -> None:
    source = _FakeSource(
        [tool("start_process", PermissionLevel.CONFIRM, properties={"command": {}})]
    )
    provider = StubProvider(
        [
            plan_call([{"id": "step_1", "description": "Start backend", "tool": "start_process"}]),
            tool_turn("start_process", {"command": "uv run uvicorn app.main:app"}),
            AIMessage(content="I could not start it; you declined."),
        ]
    )
    broker = ApprovalBroker()
    runner = build_runner(settings, provider, source, broker=broker)

    record = runner.start("Start my backend and check whether it is healthy.")
    request = await _await_pending(broker)
    broker.deny(request.request_id)
    await runner.task_store._runs[record.task_id]

    assert source.calls == []
    assert record.status is TaskStatus.ERROR
    failed = [e for e in record.events if e.type is EventType.MISSION_STEP_FAILED]
    assert len(failed) == 1
    assert "0/2" not in failed[0].message  # not treated as a retryable attempt
    assert "denied" in failed[0].message.lower()


async def test_context_from_one_step_reaches_the_next(settings: Settings) -> None:
    """A later step should know the URL an earlier step's process exposed."""
    source = _FakeSource(
        [
            tool("start_process", PermissionLevel.CONFIRM, properties={"command": {}}),
            tool("check_local_service", properties={"url": {}}),
        ],
        {
            "start_process": ToolResult(
                content="running", structured={"url": "http://127.0.0.1:8123"}
            ),
            "check_local_service": ToolResult(content="healthy"),
        },
    )
    provider = StubProvider(
        [
            plan_call(
                [
                    {"id": "step_1", "description": "Start backend", "tool": "start_process"},
                    {
                        "id": "step_2", "description": "Check health", "tool": "check_local_service",
                        "depends_on": ["step_1"],
                    },
                ]
            ),
            tool_turn("start_process", {"command": "uv run uvicorn app.main:app"}),
            AIMessage(content="Started."),
            tool_turn("check_local_service", {"url": "http://127.0.0.1:8123"}),
            AIMessage(content="Healthy."),
            AIMessage(content="Backend started and healthy."),
        ]
    )
    broker = ApprovalBroker()
    runner = build_runner(settings, provider, source, broker=broker)

    record = runner.start("Start my backend and check whether it is healthy.")
    request = await _await_pending(broker)
    broker.approve(request.request_id)
    await runner.task_store._runs[record.task_id]

    assert record.status is TaskStatus.COMPLETED
    # The 4th call is step_2's opening turn; its instruction carries step_1's URL.
    step_2_instruction = provider.calls[3][0][-1].content
    assert "http://127.0.0.1:8123" in step_2_instruction


async def test_an_unanswered_approval_times_out_without_retrying(settings: Settings) -> None:
    source = _FakeSource(
        [tool("start_process", PermissionLevel.CONFIRM, properties={"command": {}})]
    )
    provider = StubProvider(
        [
            plan_call([{"id": "step_1", "description": "Start backend", "tool": "start_process"}]),
            tool_turn("start_process", {"command": "uv run uvicorn app.main:app"}),
            AIMessage(content="Nobody answered in time."),
        ]
    )
    runner = build_runner(settings, provider, source)
    runner._settings = _with(runner._settings, permission_timeout_seconds=0.05)

    record = await runner.run("Start my backend and check whether it is healthy.")

    assert source.calls == []
    assert record.status is TaskStatus.ERROR
    failed = [e for e in record.events if e.type is EventType.MISSION_STEP_FAILED]
    assert "timed out" in failed[0].message


# --- retries -----------------------------------------------------------


async def test_a_failing_safe_step_retries_up_to_the_limit(settings: Settings) -> None:
    source = _FakeSource(
        [tool("read_file", properties={"path": {}})],
        {"read_file": ToolResult(content="not found", is_error=True)},
    )
    provider = StubProvider(
        [
            plan_call([{"id": "step_1", "description": "Read config", "tool": "read_file"}]),
            tool_turn("read_file", {"path": "~/x"}),
            AIMessage(content="Could not read it."),
            tool_turn("read_file", {"path": "~/x"}),
            AIMessage(content="Still could not read it."),
            tool_turn("read_file", {"path": "~/x"}),
            AIMessage(content="Still failing."),
        ]
    )
    runner = build_runner(settings, provider, source)

    record = await runner.run("Prepare my project for development.")

    # Bounded: the default test settings allow 2 retries -> 3 attempts total.
    assert len(source.calls) == 3
    assert record.status is TaskStatus.ERROR
    retried = [e for e in record.events if e.type is EventType.MISSION_STEP_FAILED]
    assert any("retry 1/2" in e.message for e in retried)
    assert any("retry 2/2" in e.message for e in retried)


# --- safety limits -----------------------------------------------------


async def test_max_tool_calls_stops_the_mission(settings: Settings) -> None:
    source = _FakeSource(
        [tool("read_file", properties={"path": {}})],
        {"read_file": ToolResult(content="not found", is_error=True)},
    )
    responses = []
    for _ in range(10):
        responses.append(tool_turn("read_file", {"path": "~/x"}))
        responses.append(AIMessage(content="failed"))
    provider = StubProvider(
        [plan_call([{"id": "step_1", "description": "Read", "tool": "read_file"}]), *responses]
    )
    runner = build_runner(settings, provider, source)
    # 1 retry allowed, but a tiny tool-call budget forces an early stop.
    runner._settings = _with(runner._settings, mission_max_tool_calls=2, mission_max_retries_per_step=10)

    record = await runner.run("Prepare my project for development.")

    assert record.status is TaskStatus.ERROR
    assert "max_tool_calls" in record.response
    assert len(source.calls) <= 3  # stopped promptly, not after all 10 attempts


async def test_max_runtime_stops_the_mission(settings: Settings) -> None:
    source = _FakeSource([tool("git_status")], {"git_status": ToolResult(content="clean")})
    provider = StubProvider(
        [plan_call([{"id": "step_1", "description": "Status", "tool": "git_status"}])]
    )
    runner = build_runner(settings, provider, source)
    runner._settings = _with(runner._settings, mission_max_runtime_seconds=0.0)

    record = await runner.run("Prepare my project for development.")

    assert record.status is TaskStatus.ERROR
    assert "max_runtime" in record.response


async def test_retries_exhaust_and_terminate_well_within_the_loop_guard(
    settings: Settings,
) -> None:
    """The retry bound itself is what normally ends a failing step — the loop
    guard is a backstop for a logic bug, not something ordinary behaviour
    should ever reach. This confirms the ordinary path terminates cleanly."""
    source = _FakeSource(
        [tool("read_file", properties={"path": {}})],
        {"read_file": ToolResult(content="not found", is_error=True)},
    )
    responses = [plan_call([{"id": "step_1", "description": "Read", "tool": "read_file"}])]
    for _ in range(5):
        responses.append(tool_turn("read_file", {"path": "~/x"}))
        responses.append(AIMessage(content="failed"))
    provider = StubProvider(responses)
    runner = build_runner(settings, provider, source)
    runner._settings = _with(runner._settings, mission_max_retries_per_step=4)

    record = await runner.run("Prepare my project for development.")

    assert record.status is TaskStatus.ERROR
    assert "Step(s) failed without a recovery step" in record.response
    assert len(source.calls) == 5  # 1 initial attempt + 4 retries, then terminal


def _with(settings: Settings, **changes) -> Settings:
    import dataclasses

    return dataclasses.replace(settings, **changes)


# --- cancellation --------------------------------------------------------


async def test_cancelling_a_mission_mid_step_cleans_up(settings: Settings) -> None:
    source = _FakeSource(
        [tool("start_process", PermissionLevel.CONFIRM, properties={"command": {}})]
    )
    provider = StubProvider(
        [
            plan_call([{"id": "step_1", "description": "Start backend", "tool": "start_process"}]),
            tool_turn("start_process", {"command": "uv run uvicorn app.main:app"}),
        ]
    )
    broker = ApprovalBroker()
    runner = build_runner(settings, provider, source, broker=broker)

    record = runner.start("Start my backend and check whether it is healthy.")
    request = await _await_pending(broker)

    cancelled = await runner.cancel(record.task_id)

    assert cancelled.status is TaskStatus.CANCELLED
    assert source.calls == []
    assert broker.list_pending() == []  # the pending approval was freed
    assert EventType.MISSION_CANCELLED in event_types(cancelled)


async def test_cancelling_a_completed_mission_leaves_it_alone(settings: Settings) -> None:
    source = _FakeSource([tool("git_status")], {"git_status": ToolResult(content="clean")})
    provider = StubProvider(
        [
            plan_call([{"id": "step_1", "description": "Status", "tool": "git_status"}]),
            tool_turn("git_status"),
            AIMessage(content="Clean."),
            AIMessage(content="Repo is clean."),
        ]
    )
    runner = build_runner(settings, provider, source)

    record = await runner.run("Prepare my project for development.")
    result = await runner.cancel(record.task_id)

    assert result.status is TaskStatus.COMPLETED
    assert EventType.MISSION_CANCELLED not in event_types(result)


# --- helper functions in isolation ------------------------------------


def test_run_if_eligible_always() -> None:
    mission = Mission(id="m", objective="x", task_id="t")
    dep = MissionStep(id="a", description="a", tool="x", status=StepStatus.FAILED)
    step = MissionStep(id="b", description="b", tool="y", depends_on=("a",), run_if="always")
    mission.steps = [dep, step]

    eligible, _ = _run_if_eligible(mission, step)
    assert eligible is True


def test_run_if_eligible_on_success_blocks_after_failure() -> None:
    mission = Mission(id="m", objective="x", task_id="t")
    dep = MissionStep(id="a", description="a", tool="x", status=StepStatus.FAILED)
    step = MissionStep(id="b", description="b", tool="y", depends_on=("a",), run_if="on_success")
    mission.steps = [dep, step]

    eligible, reason = _run_if_eligible(mission, step)
    assert eligible is False
    assert "did not complete successfully" in reason


def test_mission_outcome_completed_when_nothing_failed() -> None:
    mission = Mission(id="m", objective="x", task_id="t")
    mission.steps = [MissionStep(id="a", description="a", tool="x", status=StepStatus.COMPLETED)]

    status, reason = _mission_outcome(mission)
    assert status is MissionStatus.COMPLETED
    assert reason is None


def test_max_loop_iterations_is_bounded_by_steps_and_retries() -> None:
    """Defense in depth: the step loop cannot spin forever even if every
    other limit were somehow bypassed — #17's "no autonomous infinite loop"
    as an explicit, independently-checkable guarantee."""
    limits = MissionLimits(
        max_steps=30, max_retries_per_step=2, max_tool_calls=50, max_runtime_seconds=600.0
    )

    assert limits.max_loop_iterations == 30 * (2 + 1) + 10
    assert limits.max_loop_iterations < float("inf")


def test_mission_outcome_failed_without_a_handler() -> None:
    mission = Mission(id="m", objective="x", task_id="t")
    mission.steps = [MissionStep(id="a", description="a", tool="x", status=StepStatus.FAILED)]

    status, reason = _mission_outcome(mission)
    assert status is MissionStatus.FAILED
    assert "a" in reason
