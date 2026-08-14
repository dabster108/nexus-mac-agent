"""LangGraph execution: the agent/tool loop, permissions and errors."""

from __future__ import annotations

from conftest import FakeToolSource, StubProvider, tool_definition
from langchain_core.messages import AIMessage, ToolMessage

from app.agent.events import EventType
from app.agent.graph import build_agent_graph
from app.agent.state import initial_state
from app.core.errors import ModelError
from app.models.base import ModelProvider, ToolSpec
from app.tools.permissions import PermissionLevel, PermissionPolicy
from app.tools.registry import ToolRegistry, ToolResult

TASK_ID = "task_test"


def tool_call(name: str, args: dict | None = None, call_id: str = "call_1") -> dict:
    return {"name": name, "args": args or {}, "id": call_id, "type": "tool_call"}


async def build_registry(source: FakeToolSource) -> ToolRegistry:
    registry = ToolRegistry([source])
    await registry.refresh()
    return registry


def event_types(state: dict) -> list[str]:
    return [str(event.type) for event in state["execution_events"]]


async def test_answering_without_tools_ends_immediately() -> None:
    provider = StubProvider([AIMessage(content="Hello.")])
    registry = await build_registry(FakeToolSource([tool_definition("battery_status")]))
    graph = build_agent_graph(
        provider=provider, registry=registry, policy=PermissionPolicy()
    )

    state = await graph.ainvoke(initial_state(TASK_ID, "hi"))

    assert state["completed"] is True
    assert event_types(state) == [EventType.AGENT_MESSAGE]
    assert len(provider.calls) == 1


async def test_tool_loop_runs_the_tool_and_comes_back_to_the_agent() -> None:
    provider = StubProvider(
        [
            AIMessage(content="", tool_calls=[tool_call("battery_status")]),
            AIMessage(content="Your battery is at 87 percent."),
        ]
    )
    source = FakeToolSource(
        [tool_definition("battery_status")],
        {"battery_status": ToolResult(content="87%", structured={"percentage": 87})},
    )
    graph = build_agent_graph(
        provider=provider,
        registry=await build_registry(source),
        policy=PermissionPolicy(),
    )

    state = await graph.ainvoke(initial_state(TASK_ID, "what is my battery?"))

    assert source.calls == [("battery_status", {})]
    assert state["completed"] is True
    assert state["tool_results"][0]["success"] is True
    assert state["tool_results"][0]["content"] == "87%"
    assert event_types(state) == [
        EventType.TOOL_REQUESTED,
        EventType.TOOL_STARTED,
        EventType.TOOL_COMPLETED,
        EventType.AGENT_MESSAGE,
    ]
    assert state["messages"][-1].content == "Your battery is at 87 percent."


async def test_the_model_only_ever_sees_the_registry_tools() -> None:
    provider = StubProvider([AIMessage(content="ok")])
    source = FakeToolSource(
        [
            tool_definition("battery_status", PermissionLevel.SAFE),
            tool_definition("delete_file", PermissionLevel.RESTRICTED),
        ]
    )
    graph = build_agent_graph(
        provider=provider,
        registry=await build_registry(source),
        policy=PermissionPolicy(),
    )

    await graph.ainvoke(initial_state(TASK_ID, "hi"))

    offered: list[ToolSpec] = provider.calls[0][1]
    assert [spec.name for spec in offered] == ["battery_status"]


async def test_a_confirm_tool_halts_the_run_and_is_not_executed() -> None:
    provider = StubProvider(
        [AIMessage(content="", tool_calls=[tool_call("open_application", {"name": "Code"})])]
    )
    source = FakeToolSource([tool_definition("open_application", PermissionLevel.CONFIRM)])
    graph = build_agent_graph(
        provider=provider,
        registry=await build_registry(source),
        policy=PermissionPolicy(),
    )

    state = await graph.ainvoke(initial_state(TASK_ID, "open vs code"))

    assert source.calls == []
    assert state["requires_permission"] is True
    assert state["permission_request"]["tool"] == "open_application"
    assert EventType.PERMISSION_REQUIRED in event_types(state)
    # Halted, so the model is not asked a second time.
    assert len(provider.calls) == 1


async def test_an_approved_confirm_tool_runs() -> None:
    provider = StubProvider(
        [
            AIMessage(content="", tool_calls=[tool_call("open_application", {"name": "Code"})]),
            AIMessage(content="Opened VS Code."),
        ]
    )
    source = FakeToolSource([tool_definition("open_application", PermissionLevel.CONFIRM)])
    graph = build_agent_graph(
        provider=provider,
        registry=await build_registry(source),
        policy=PermissionPolicy(["open_application"]),
    )

    state = await graph.ainvoke(initial_state(TASK_ID, "open vs code"))

    assert source.calls == [("open_application", {"name": "Code"})]
    assert state["requires_permission"] is False


async def test_a_restricted_tool_is_refused_and_the_agent_explains() -> None:
    provider = StubProvider(
        [
            AIMessage(content="", tool_calls=[tool_call("delete_file", {"path": "/tmp/x"})]),
            AIMessage(content="I am not allowed to delete files."),
        ]
    )
    # Reachable only because the model named it directly; it is never offered.
    source = FakeToolSource([tool_definition("delete_file", PermissionLevel.RESTRICTED)])
    graph = build_agent_graph(
        provider=provider,
        registry=await build_registry(source),
        policy=PermissionPolicy(),
    )

    state = await graph.ainvoke(initial_state(TASK_ID, "delete my files"))

    assert source.calls == []
    assert state["tool_results"][0]["success"] is False
    assert state["messages"][-1].content == "I am not allowed to delete files."


async def test_a_tool_the_model_hallucinated_is_reported_back() -> None:
    provider = StubProvider(
        [
            AIMessage(content="", tool_calls=[tool_call("make_coffee")]),
            AIMessage(content="I cannot do that."),
        ]
    )
    graph = build_agent_graph(
        provider=provider,
        registry=await build_registry(FakeToolSource([tool_definition("system_info")])),
        policy=PermissionPolicy(),
    )

    state = await graph.ainvoke(initial_state(TASK_ID, "make coffee"))

    assert "not an available tool" in state["tool_results"][0]["content"]


async def test_a_model_error_becomes_a_structured_task_error() -> None:
    class FailingProvider(ModelProvider):
        name = "failing"

        @property
        def model(self) -> str:
            return "failing-model"

        async def ainvoke(self, messages, tools=()):  # type: ignore[no-untyped-def]
            raise ModelError("The Groq model could not be reached.", detail="boom")

    graph = build_agent_graph(
        provider=FailingProvider(),
        registry=await build_registry(FakeToolSource([])),
        policy=PermissionPolicy(),
    )

    state = await graph.ainvoke(initial_state(TASK_ID, "hi"))

    assert state["error"] == {
        "code": "MODEL_ERROR",
        "message": "The Groq model could not be reached.",
    }
    assert event_types(state) == [EventType.TASK_ERROR]


async def test_the_step_budget_stops_a_tool_loop() -> None:
    # The model would keep calling the tool forever if it were allowed to.
    provider = StubProvider(
        [AIMessage(content="", tool_calls=[tool_call("system_info")]) for _ in range(10)]
    )
    source = FakeToolSource([tool_definition("system_info")])
    graph = build_agent_graph(
        provider=provider,
        registry=await build_registry(source),
        policy=PermissionPolicy(),
        max_iterations=2,
    )

    state = await graph.ainvoke(initial_state(TASK_ID, "loop"))

    assert state["completed"] is True
    assert len(source.calls) == 2
    # On the final turn no tools are offered, forcing a text answer.
    assert provider.calls[-1][1] == []


async def test_the_final_turn_tells_the_model_to_stop_calling_tools() -> None:
    # A live-observed failure: with no tools offered, the model wrote one out
    # as literal text instead of answering. The final system prompt must say
    # plainly that this turn is answer-only.
    provider = StubProvider(
        [AIMessage(content="", tool_calls=[tool_call("system_info")]) for _ in range(10)]
    )
    source = FakeToolSource([tool_definition("system_info")])
    graph = build_agent_graph(
        provider=provider,
        registry=await build_registry(source),
        policy=PermissionPolicy(),
        max_iterations=2,
    )

    await graph.ainvoke(initial_state(TASK_ID, "loop"))

    first_system_prompt = provider.calls[0][0][0].content
    final_system_prompt = provider.calls[-1][0][0].content
    assert "you have used all the tool calls" in final_system_prompt.lower()
    assert "you have used all the tool calls" not in first_system_prompt.lower()


async def test_one_turn_cannot_run_an_unbounded_number_of_tools() -> None:
    # A live-observed failure: the model emitted ~250 copies of the same call
    # in a single response and every one of them was executed. The step budget
    # counts turns, so it is no defence against one runaway turn.
    from app.agent.nodes import MAX_TOOL_CALLS_PER_TURN

    # Distinct arguments, so this exercises the cap rather than de-duplication.
    flood = [
        tool_call("read_file", {"path": f"f{i}.txt"}, call_id=f"call_{i}")
        for i in range(MAX_TOOL_CALLS_PER_TURN * 50)
    ]
    provider = StubProvider(
        [AIMessage(content="", tool_calls=flood), AIMessage(content="Done.")]
    )
    source = FakeToolSource([tool_definition("read_file")])
    graph = build_agent_graph(
        provider=provider, registry=await build_registry(source), policy=PermissionPolicy()
    )

    state = await graph.ainvoke(initial_state(TASK_ID, "flood"))

    assert len(source.calls) == MAX_TOOL_CALLS_PER_TURN
    assert state["completed"] is True
    # Every executed call is answered, so the transcript stays well-formed.
    executed = state["messages"][1].tool_calls
    replies = [m for m in state["messages"] if isinstance(m, ToolMessage)]
    assert len(executed) == MAX_TOOL_CALLS_PER_TURN
    assert {m.tool_call_id for m in replies} == {c["id"] for c in executed}


async def test_identical_calls_in_one_turn_run_once() -> None:
    # Repeating a call verbatim tells the model nothing new, and each extra
    # result is transcript the next request has to carry — which is how a
    # repetitive turn ends in a provider rate-limit error.
    repeats = [tool_call("list_processes", call_id=f"call_{i}") for i in range(4)]
    provider = StubProvider(
        [AIMessage(content="", tool_calls=repeats), AIMessage(content="Done.")]
    )
    source = FakeToolSource([tool_definition("list_processes")])
    graph = build_agent_graph(
        provider=provider, registry=await build_registry(source), policy=PermissionPolicy()
    )

    state = await graph.ainvoke(initial_state(TASK_ID, "what is running?"))

    assert source.calls == [("list_processes", {})]
    replies = [m for m in state["messages"] if isinstance(m, ToolMessage)]
    assert len(replies) == 1


async def test_the_same_tool_with_different_arguments_still_runs_twice() -> None:
    calls = [
        tool_call("read_file", {"path": "a.txt"}, call_id="c1"),
        tool_call("read_file", {"path": "b.txt"}, call_id="c2"),
    ]
    provider = StubProvider(
        [AIMessage(content="", tool_calls=calls), AIMessage(content="Done.")]
    )
    source = FakeToolSource([tool_definition("read_file")])
    graph = build_agent_graph(
        provider=provider, registry=await build_registry(source), policy=PermissionPolicy()
    )

    await graph.ainvoke(initial_state(TASK_ID, "read both"))

    assert source.calls == [
        ("read_file", {"path": "a.txt"}),
        ("read_file", {"path": "b.txt"}),
    ]


def test_the_system_prompt_maps_forget_language_to_delete_memory() -> None:
    # A live-observed failure: "Forget everything you know about NEXUS." was
    # answered conversationally with no delete_memory call at all. The prompt
    # must say explicitly that "forget" is an instruction, not small talk.
    from app.agent.nodes import SYSTEM_PROMPT

    prompt = SYSTEM_PROMPT.lower()
    assert "forget" in prompt
    assert "delete_memory" in prompt
