"""The permission request lifecycle, end to end.

Covers both halves: the HTTP surface, and the agent actually waiting on and
reacting to the user's decision.
"""

from __future__ import annotations

import asyncio

import pytest
from conftest import FakeToolSource, StubProvider, tool_definition
from fastapi.testclient import TestClient
from langchain_core.messages import AIMessage

from app.agent.approvals import (
    ApprovalAlreadyResolved,
    ApprovalBroker,
    ApprovalNotFound,
    ApprovalStatus,
)
from app.agent.events import EventType
from app.agent.graph import build_agent_graph
from app.agent.state import initial_state
from app.agent.tasks import TaskStatus
from app.core.config import Settings, get_settings
from app.main import create_app
from app.tools.permissions import PermissionLevel, PermissionPolicy
from app.tools.registry import ToolRegistry

TASK_ID = "task_test"


@pytest.fixture
def client(settings: Settings) -> TestClient:
    app = create_app(settings)
    app.dependency_overrides[get_settings] = lambda: settings
    return TestClient(app)


def open_app_call() -> dict:
    return {
        "name": "open_application",
        "args": {"name": "Code"},
        "id": "call_1",
        "type": "tool_call",
    }


async def build_graph(broker: ApprovalBroker, source: FakeToolSource, **kwargs):
    registry = ToolRegistry([source])
    await registry.refresh()
    return build_agent_graph(
        provider=kwargs.pop("provider"),
        registry=registry,
        policy=kwargs.pop("policy", PermissionPolicy()),
        broker=broker,
        permission_timeout=kwargs.pop("permission_timeout", 2.0),
        **kwargs,
    )


# --- HTTP surface ----------------------------------------------------------


def test_pending_is_empty_to_start_with(client: TestClient) -> None:
    assert client.get("/api/permissions/pending").json() == {"requests": []}


def test_pending_lists_a_request(client: TestClient, broker: ApprovalBroker) -> None:
    broker.create(
        task_id="task_1",
        tool="execute_command",
        permission=PermissionLevel.CONFIRM,
        description="Run npm run dev",
        arguments={"command": "npm run dev"},
    )

    body = client.get("/api/permissions/pending").json()

    assert len(body["requests"]) == 1
    request = body["requests"][0]
    assert request["request_id"].startswith("perm_")
    assert request["task_id"] == "task_1"
    assert request["tool"] == "execute_command"
    assert request["permission"] == "CONFIRM"
    assert request["description"] == "Run npm run dev"
    # The user has to see what they are approving.
    assert request["arguments"] == {"command": "npm run dev"}
    assert request["status"] == "pending"


def test_approve_changes_the_state(client: TestClient, broker: ApprovalBroker) -> None:
    request = broker.create(
        task_id="task_1",
        tool="open_application",
        permission=PermissionLevel.CONFIRM,
        description="Open an app",
    )

    body = client.post(f"/api/permissions/{request.request_id}/approve").json()

    assert body == {"request_id": request.request_id, "status": "approved"}
    assert request.status is ApprovalStatus.APPROVED
    assert broker.list_pending() == []


def test_deny_changes_the_state(client: TestClient, broker: ApprovalBroker) -> None:
    request = broker.create(
        task_id="task_1",
        tool="open_application",
        permission=PermissionLevel.CONFIRM,
        description="Open an app",
    )

    body = client.post(f"/api/permissions/{request.request_id}/deny").json()

    assert body == {"request_id": request.request_id, "status": "denied"}
    assert request.status is ApprovalStatus.DENIED


def test_unknown_request_is_404(client: TestClient) -> None:
    for action in ("approve", "deny"):
        response = client.post(f"/api/permissions/perm_nope/{action}")
        assert response.status_code == 404
        assert response.json()["error"]["code"] == "VALIDATION_ERROR"


def test_deciding_twice_is_409(client: TestClient, broker: ApprovalBroker) -> None:
    request = broker.create(
        task_id="task_1",
        tool="open_application",
        permission=PermissionLevel.CONFIRM,
        description="Open an app",
    )
    client.post(f"/api/permissions/{request.request_id}/approve")

    response = client.post(f"/api/permissions/{request.request_id}/deny")

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "PERMISSION_ERROR"


# --- broker semantics ------------------------------------------------------


def test_the_broker_raises_for_unknown_ids() -> None:
    broker = ApprovalBroker()

    with pytest.raises(ApprovalNotFound):
        broker.approve("perm_nope")


def test_the_broker_refuses_to_redecide() -> None:
    broker = ApprovalBroker()
    request = broker.create(
        task_id="t", tool="x", permission=PermissionLevel.CONFIRM, description="x"
    )
    broker.deny(request.request_id)

    with pytest.raises(ApprovalAlreadyResolved):
        broker.approve(request.request_id)


async def test_waiting_times_out() -> None:
    broker = ApprovalBroker()
    request = broker.create(
        task_id="t", tool="x", permission=PermissionLevel.CONFIRM, description="x"
    )

    assert await broker.wait(request, timeout=0.05) is ApprovalStatus.EXPIRED
    assert broker.list_pending() == []


# --- the agent actually waits ----------------------------------------------


async def test_the_agent_waits_and_runs_the_tool_once_approved(
    broker: ApprovalBroker,
) -> None:
    provider = StubProvider(
        [
            AIMessage(content="", tool_calls=[open_app_call()]),
            AIMessage(content="Opened VS Code."),
        ]
    )
    source = FakeToolSource(
        [tool_definition("open_application", PermissionLevel.CONFIRM)]
    )
    graph = await build_graph(broker, source, provider=provider)

    run = asyncio.create_task(graph.ainvoke(initial_state(TASK_ID, "open vs code")))

    # The request appears while the run is still blocked on it.
    request = await _await_pending(broker)
    assert source.calls == []
    assert not run.done()

    broker.approve(request.request_id)
    state = await run

    assert source.calls == [("open_application", {"name": "Code"})]
    assert state["messages"][-1].content == "Opened VS Code."


async def test_a_denial_reaches_the_agent_gracefully(broker: ApprovalBroker) -> None:
    provider = StubProvider(
        [
            AIMessage(content="", tool_calls=[open_app_call()]),
            AIMessage(content="I did not open it, since you declined."),
        ]
    )
    source = FakeToolSource(
        [tool_definition("open_application", PermissionLevel.CONFIRM)]
    )
    graph = await build_graph(broker, source, provider=provider)

    run = asyncio.create_task(graph.ainvoke(initial_state(TASK_ID, "open vs code")))
    request = await _await_pending(broker)
    broker.deny(request.request_id)
    state = await run

    assert source.calls == []
    result = state["tool_results"][0]
    assert result["success"] is False
    assert result["content"] == "The user denied permission to run 'open_application'."
    # The model got to explain, rather than the run dying.
    assert state["messages"][-1].content == "I did not open it, since you declined."


async def test_an_unanswered_request_expires_instead_of_hanging(
    broker: ApprovalBroker,
) -> None:
    provider = StubProvider(
        [
            AIMessage(content="", tool_calls=[open_app_call()]),
            AIMessage(content="I never got permission."),
        ]
    )
    source = FakeToolSource(
        [tool_definition("open_application", PermissionLevel.CONFIRM)]
    )
    graph = await build_graph(broker, source, provider=provider, permission_timeout=0.05)

    state = await graph.ainvoke(initial_state(TASK_ID, "open vs code"))

    assert source.calls == []
    assert "timed out" in state["tool_results"][0]["content"]


async def test_a_pre_approved_tool_never_creates_a_request(
    broker: ApprovalBroker,
) -> None:
    provider = StubProvider(
        [
            AIMessage(content="", tool_calls=[open_app_call()]),
            AIMessage(content="Opened VS Code."),
        ]
    )
    source = FakeToolSource(
        [tool_definition("open_application", PermissionLevel.CONFIRM)]
    )
    graph = await build_graph(
        broker,
        source,
        provider=provider,
        policy=PermissionPolicy(["open_application"]),
    )

    await graph.ainvoke(initial_state(TASK_ID, "open vs code"))

    assert source.calls == [("open_application", {"name": "Code"})]
    assert broker.list_pending() == []


async def test_a_restricted_tool_never_reaches_the_broker(
    broker: ApprovalBroker,
) -> None:
    provider = StubProvider(
        [
            AIMessage(
                content="",
                tool_calls=[
                    {"name": "delete_file", "args": {}, "id": "c1", "type": "tool_call"}
                ],
            ),
            AIMessage(content="I cannot do that."),
        ]
    )
    source = FakeToolSource([tool_definition("delete_file", PermissionLevel.RESTRICTED)])
    graph = await build_graph(broker, source, provider=provider)

    state = await graph.ainvoke(initial_state(TASK_ID, "delete everything"))

    # Restricted is refused outright — the user is never even asked.
    assert broker.list_pending() == []
    assert source.calls == []
    assert state["tool_results"][0]["success"] is False


# --- runner integration ----------------------------------------------------


async def test_the_task_reports_that_it_is_waiting(
    settings: Settings, broker: ApprovalBroker
) -> None:
    from app.agent.runner import AgentRunner
    from app.agent.tasks import TaskStore
    from app.mcp.registry import MCPServerRegistry
    from app.models.router import ModelRouter

    provider = StubProvider(
        [
            AIMessage(content="", tool_calls=[open_app_call()]),
            AIMessage(content="Opened VS Code."),
        ]
    )
    store = TaskStore()
    runner = AgentRunner(
        settings=settings,
        router=ModelRouter(settings, {"groq": lambda _s: provider}),
        task_store=store,
        server_registry=MCPServerRegistry([]),
        broker=broker,
    )
    runner._servers = _SourceRegistry(
        FakeToolSource([tool_definition("open_application", PermissionLevel.CONFIRM)])
    )

    record = runner.start("open vs code")
    request = await _await_pending(broker)

    assert record.status is TaskStatus.PERMISSION_REQUIRED
    assert any(
        event.type is EventType.PERMISSION_REQUIRED
        and event.data.get("request_id") == request.request_id
        for event in record.events
    )

    broker.approve(request.request_id)
    await store._runs[record.task_id]

    assert record.status is TaskStatus.COMPLETED
    assert record.response == "Opened VS Code."


class _SourceRegistry:
    """An MCPServerRegistry stand-in that yields an in-process source."""

    def __init__(self, source: FakeToolSource) -> None:
        self._source = source

    async def open_sources(self, _stack) -> list:
        return [self._source]


async def _await_pending(broker: ApprovalBroker, timeout: float = 2.0):
    """Wait until a request shows up, so tests never race the agent."""
    async with asyncio.timeout(timeout):
        while not broker.list_pending():
            await asyncio.sleep(0.01)
    return broker.list_pending()[0]


# --- the approval prompt ---------------------------------------------------


def test_the_prompt_is_a_single_readable_sentence() -> None:
    from app.agent.approvals import describe

    prompt = describe(
        "open_application",
        "Open an installed macOS application by name. "
        "Examples: 'Visual Studio Code', 'Safari', 'Finder'.",
        {"application": "Visual Studio Code"},
    )

    # One sentence plus the arguments — the model-facing examples are dropped,
    # and values are shown plainly rather than as Python reprs.
    assert prompt == (
        "Open an installed macOS application by name (application: Visual Studio Code)"
    )


def test_the_prompt_survives_a_tool_with_no_description() -> None:
    from app.agent.approvals import describe

    assert describe("some_tool", "", {}) == "Run some_tool"


# --- a decision sticks for the run -----------------------------------------


async def test_a_denied_tool_is_not_asked_about_twice(broker: ApprovalBroker) -> None:
    """A model that retries must not re-prompt the user each iteration."""
    provider = StubProvider(
        [
            AIMessage(content="", tool_calls=[open_app_call()]),
            AIMessage(content="", tool_calls=[open_app_call()]),  # retries
            AIMessage(content="I could not open it; you declined."),
        ]
    )
    source = FakeToolSource(
        [tool_definition("open_application", PermissionLevel.CONFIRM)]
    )
    graph = await build_graph(broker, source, provider=provider)

    run = asyncio.create_task(graph.ainvoke(initial_state(TASK_ID, "open vs code")))
    request = await _await_pending(broker)
    broker.deny(request.request_id)
    state = await run

    # Asked once, refused once, never asked again.
    permission_events = [
        event
        for event in state["execution_events"]
        if event.type is EventType.PERMISSION_REQUIRED
    ]
    assert len(permission_events) == 1
    assert broker.list_pending() == []
    assert source.calls == []
    assert "Do not ask again" in state["tool_results"][1]["content"]


async def test_an_expired_request_is_not_retried(broker: ApprovalBroker) -> None:
    provider = StubProvider(
        [
            AIMessage(content="", tool_calls=[open_app_call()]),
            AIMessage(content="", tool_calls=[open_app_call()]),
            AIMessage(content="Nobody answered, so I stopped."),
        ]
    )
    source = FakeToolSource(
        [tool_definition("open_application", PermissionLevel.CONFIRM)]
    )
    graph = await build_graph(broker, source, provider=provider, permission_timeout=0.05)

    state = await graph.ainvoke(initial_state(TASK_ID, "open vs code"))

    # One timeout, not one per iteration.
    permission_events = [
        event
        for event in state["execution_events"]
        if event.type is EventType.PERMISSION_REQUIRED
    ]
    assert len(permission_events) == 1
    assert source.calls == []


async def test_a_denial_in_one_task_does_not_affect_another(
    broker: ApprovalBroker,
) -> None:
    denied = broker.create(
        task_id="task_a",
        tool="open_application",
        permission=PermissionLevel.CONFIRM,
        description="Open an app",
    )
    broker.deny(denied.request_id)

    assert broker.previous_refusal("task_a", "open_application") is ApprovalStatus.DENIED
    assert broker.previous_refusal("task_b", "open_application") is None
    # Nor a different tool in the same task.
    assert broker.previous_refusal("task_a", "write_file") is None


async def test_an_approval_is_not_sticky(broker: ApprovalBroker) -> None:
    approved = broker.create(
        task_id="task_a",
        tool="open_application",
        permission=PermissionLevel.CONFIRM,
        description="Open an app",
    )
    broker.approve(approved.request_id)

    # Approving once must not silently authorise every later call.
    assert broker.previous_refusal("task_a", "open_application") is None


# --- regression: the permission boundary after adding run_command ---------


async def test_run_command_still_goes_through_the_approval_broker(
    broker: ApprovalBroker,
) -> None:
    """A second CONFIRM tool must use the same broker, not its own mechanism."""
    call = {
        "name": "run_command",
        "args": {"command": "pytest", "working_directory": "~/Projects/nexus"},
        "id": "call_1",
        "type": "tool_call",
    }
    provider = StubProvider(
        [
            AIMessage(content="", tool_calls=[call]),
            AIMessage(content="The tests passed."),
        ]
    )
    source = FakeToolSource([tool_definition("run_command", PermissionLevel.CONFIRM)])
    graph = await build_graph(broker, source, provider=provider)

    run = asyncio.create_task(graph.ainvoke(initial_state(TASK_ID, "run the tests")))
    request = await _await_pending(broker)

    assert request.tool == "run_command"
    assert request.arguments == {
        "command": "pytest",
        "working_directory": "~/Projects/nexus",
    }
    assert source.calls == []  # nothing ran while waiting

    broker.approve(request.request_id)
    await run

    assert source.calls == [
        ("run_command", {"command": "pytest", "working_directory": "~/Projects/nexus"})
    ]


async def test_denying_a_command_stops_it_running(broker: ApprovalBroker) -> None:
    call = {
        "name": "run_command",
        "args": {"command": "npm run build", "working_directory": "~/p"},
        "id": "call_1",
        "type": "tool_call",
    }
    provider = StubProvider(
        [
            AIMessage(content="", tool_calls=[call]),
            AIMessage(content="I did not run it, since you declined."),
        ]
    )
    source = FakeToolSource([tool_definition("run_command", PermissionLevel.CONFIRM)])
    graph = await build_graph(broker, source, provider=provider)

    run = asyncio.create_task(graph.ainvoke(initial_state(TASK_ID, "build it")))
    request = await _await_pending(broker)
    broker.deny(request.request_id)
    state = await run

    assert source.calls == []
    assert state["tool_results"][0]["content"] == (
        "The user denied permission to run 'run_command'."
    )


async def test_a_command_approval_uses_the_declared_prompt(
    broker: ApprovalBroker,
) -> None:
    """§15: the request must read as a sentence, not a Python object."""
    from app.tools.registry import ToolDefinition

    definition = ToolDefinition(
        name="run_command",
        description="Run an approved developer command in a project directory.",
        input_schema={},
        source="nexus-mac",
        permission=PermissionLevel.CONFIRM,
        prompt_template="Run {command} in {working_directory}",
    )
    call = {
        "name": "run_command",
        "args": {"command": "npm run build", "working_directory": "~/Projects/frontend"},
        "id": "call_1",
        "type": "tool_call",
    }
    provider = StubProvider(
        [AIMessage(content="", tool_calls=[call]), AIMessage(content="done")]
    )
    source = FakeToolSource([definition])
    graph = await build_graph(broker, source, provider=provider)

    run = asyncio.create_task(graph.ainvoke(initial_state(TASK_ID, "build it")))
    request = await _await_pending(broker)

    assert request.description == "Run npm run build in ~/Projects/frontend"
    assert "ToolDefinition" not in request.description
    assert "{" not in request.description

    broker.deny(request.request_id)
    await run


# --- process tools respect the permission boundary ------------------------


async def test_process_tools_are_split_correctly(settings: Settings) -> None:
    """Read-only process views must not prompt; start/stop must."""
    from contextlib import AsyncExitStack

    from app.mcp.registry import MCPServerRegistry

    async with AsyncExitStack() as stack:
        sources = await MCPServerRegistry.from_settings(settings).open_sources(stack)
        registry = ToolRegistry(sources)
        await registry.refresh()

        policy = PermissionPolicy()
        for name in ("list_processes", "process_status", "process_logs", "check_local_service"):
            decision = policy.evaluate(name, registry.require(name).permission)
            assert decision.allowed is True, name

        for name in ("start_process", "stop_process"):
            decision = policy.evaluate(name, registry.require(name).permission)
            assert decision.allowed is False, name
            assert decision.requires_confirmation is True, name


async def test_starting_a_process_waits_for_approval(broker: ApprovalBroker) -> None:
    call = {
        "name": "start_process",
        "args": {"command": "npm run dev", "working_directory": "~/Projects/frontend"},
        "id": "call_1",
        "type": "tool_call",
    }
    provider = StubProvider(
        [AIMessage(content="", tool_calls=[call]), AIMessage(content="Started.")]
    )
    from app.tools.registry import ToolDefinition

    definition = ToolDefinition(
        name="start_process",
        description="Start a long-running development server.",
        input_schema={},
        source="nexus-mac",
        permission=PermissionLevel.CONFIRM,
        prompt_template="Start {command} in {working_directory}",
    )
    source = FakeToolSource([definition])
    graph = await build_graph(broker, source, provider=provider)

    run = asyncio.create_task(graph.ainvoke(initial_state(TASK_ID, "start my frontend")))
    request = await _await_pending(broker)

    assert request.description == "Start npm run dev in ~/Projects/frontend"
    assert source.calls == []  # nothing started while waiting

    broker.approve(request.request_id)
    await run

    assert source.calls == [
        ("start_process", {"command": "npm run dev", "working_directory": "~/Projects/frontend"})
    ]


async def test_stopping_a_process_waits_for_approval(broker: ApprovalBroker) -> None:
    call = {
        "name": "stop_process",
        "args": {"process_id": "proc_abc123"},
        "id": "call_1",
        "type": "tool_call",
    }
    provider = StubProvider(
        [AIMessage(content="", tool_calls=[call]), AIMessage(content="Stopped.")]
    )
    from app.tools.registry import ToolDefinition

    definition = ToolDefinition(
        name="stop_process",
        description="Stop a development process NEXUS started.",
        input_schema={},
        source="nexus-mac",
        permission=PermissionLevel.CONFIRM,
        prompt_template="Stop the managed process {process_id}",
    )
    graph = await build_graph(broker, FakeToolSource([definition]), provider=provider)

    run = asyncio.create_task(graph.ainvoke(initial_state(TASK_ID, "stop the server")))
    request = await _await_pending(broker)

    assert request.description == "Stop the managed process proc_abc123"

    broker.deny(request.request_id)
    await run
