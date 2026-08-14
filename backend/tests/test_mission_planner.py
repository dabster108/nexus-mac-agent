"""The mission planner: forcing structured output, then validating it hard.

The model never gets a free pass — every plan is checked against the live
tool registry before a single step is allowed to run.
"""

from __future__ import annotations

from conftest import StubProvider
from langchain_core.messages import AIMessage

from app.mission.planner import (
    MAX_PLANNING_ATTEMPTS,
    PLANNER_TOOL_NAME,
    MissionPlanningError,
    create_plan,
)
from app.tools.permissions import PermissionLevel
from app.tools.registry import ToolDefinition, ToolRegistry


def _tool(
    name: str,
    permission: PermissionLevel = PermissionLevel.SAFE,
    properties: dict | None = None,
) -> ToolDefinition:
    return ToolDefinition(
        name=name,
        description=f"Test tool {name}",
        input_schema={"type": "object", "properties": properties or {}},
        source="fake",
        permission=permission,
    )


async def build_registry(*tools: ToolDefinition) -> ToolRegistry:
    class _Source:
        name = "fake"

        async def list_tools(self):
            return tools

        async def call_tool(self, name, arguments):  # pragma: no cover - unused
            raise NotImplementedError

    registry = ToolRegistry([_Source()])
    await registry.refresh()
    return registry


def plan_call(steps: list[dict], objective: str = "Do the thing.") -> AIMessage:
    return AIMessage(
        content="",
        tool_calls=[
            {
                "name": PLANNER_TOOL_NAME,
                "args": {"objective": objective, "steps": steps},
                "id": "call_1",
                "type": "tool_call",
            }
        ],
    )


# --- a valid plan ------------------------------------------------------


async def test_a_valid_plan_is_accepted() -> None:
    registry = await build_registry(_tool("git_status"), _tool("read_file"))
    provider = StubProvider(
        [
            plan_call(
                [
                    {"id": "step_1", "description": "Check status", "tool": "git_status"},
                    {
                        "id": "step_2",
                        "description": "Read the README",
                        "tool": "read_file",
                        "depends_on": ["step_1"],
                    },
                ],
                objective="Inspect the repo",
            )
        ]
    )

    plan = await create_plan(provider, registry, "Inspect the repo", max_steps=10)

    assert plan.objective == "Inspect the repo"
    assert [step.id for step in plan.steps] == ["step_1", "step_2"]
    assert plan.steps[1].depends_on == ("step_1",)
    # Forced tool choice, not left to the model's discretion.
    assert provider.calls[0][2] == PLANNER_TOOL_NAME


async def test_run_if_and_arguments_survive_validation() -> None:
    registry = await build_registry(
        _tool("run_command", properties={"command": {}, "working_directory": {}})
    )
    provider = StubProvider(
        [
            plan_call(
                [
                    {
                        "id": "step_1",
                        "description": "Run tests",
                        "tool": "run_command",
                        "arguments": {"command": "pytest", "working_directory": "~/p"},
                        "run_if": "on_success",
                    }
                ]
            )
        ]
    )

    plan = await create_plan(provider, registry, "Run tests", max_steps=10)

    assert plan.steps[0].arguments == {"command": "pytest", "working_directory": "~/p"}
    assert plan.steps[0].run_if == "on_success"


# --- unknown tool --------------------------------------------------------


async def test_an_unknown_tool_is_rejected_and_not_retried_forever() -> None:
    registry = await build_registry(_tool("git_status"))
    provider = StubProvider(
        [plan_call([{"id": "step_1", "description": "x", "tool": "make_coffee"}])] * 5
    )

    try:
        await create_plan(provider, registry, "x", max_steps=10)
        raise AssertionError("expected MissionPlanningError")
    except MissionPlanningError as exc:
        assert "make_coffee" in exc.message

    # Bounded: exactly the retry budget, never an open-ended loop.
    assert len(provider.calls) == MAX_PLANNING_ATTEMPTS


async def test_a_restricted_tool_cannot_be_planned() -> None:
    registry = await build_registry(
        _tool("delete_everything", PermissionLevel.RESTRICTED), _tool("git_status")
    )
    provider = StubProvider(
        [plan_call([{"id": "step_1", "description": "x", "tool": "delete_everything"}])] * MAX_PLANNING_ATTEMPTS
    )

    try:
        await create_plan(provider, registry, "x", max_steps=10)
        raise AssertionError("expected MissionPlanningError")
    except MissionPlanningError as exc:
        assert "delete_everything" in exc.message

    # Never even offered as a valid choice, so the model never sees it.
    tools_offered = provider.calls[0][1]
    schema = tools_offered[0].input_schema
    assert "delete_everything" not in schema["properties"]["steps"]["items"]["properties"]["tool"]["enum"]


async def test_a_registry_with_only_restricted_tools_cannot_be_planned() -> None:
    registry = await build_registry(_tool("delete_everything", PermissionLevel.RESTRICTED))
    provider = StubProvider([])

    try:
        await create_plan(provider, registry, "x", max_steps=10)
        raise AssertionError("expected MissionPlanningError")
    except MissionPlanningError as exc:
        assert "No tools" in exc.message
    # Rejected before ever asking the model.
    assert provider.calls == []


async def test_recovers_from_a_malformed_generation() -> None:
    """A live-observed failure mode: a smaller model's forced tool call comes
    back with invalid JSON (an unquoted key, say) and the vendor rejects the
    whole generation as a ModelError before it ever becomes a tool_call. That
    must not sink the mission on one bad attempt — it gets the same bounded
    retry a semantically-invalid plan does."""
    from app.core.errors import ModelError

    class _FlakyThenGood(StubProvider):
        async def ainvoke(self, messages, tools=(), *, tool_choice=None):
            self.calls.append((list(messages), list(tools), tool_choice))
            if len(self.calls) == 1:
                raise ModelError("The Groq model could not be reached.")
            return plan_call([{"id": "step_1", "description": "x", "tool": "git_status"}])

    registry = await build_registry(_tool("git_status"))
    provider = _FlakyThenGood([])

    plan = await create_plan(provider, registry, "x", max_steps=10)

    assert plan.steps[0].tool == "git_status"
    assert len(provider.calls) == 2
    assert "well-formed" in provider.calls[1][0][-1].content


async def test_a_persistently_malformed_generation_still_raises_cleanly() -> None:
    from app.core.errors import ModelError

    class _AlwaysFlaky(StubProvider):
        async def ainvoke(self, messages, tools=(), *, tool_choice=None):
            self.calls.append((list(messages), list(tools), tool_choice))
            raise ModelError("The Groq model could not be reached.")

    registry = await build_registry(_tool("git_status"))
    provider = _AlwaysFlaky([])

    try:
        await create_plan(provider, registry, "x", max_steps=10)
        raise AssertionError("expected MissionPlanningError")
    except MissionPlanningError as exc:
        assert "malformed" in exc.message

    assert len(provider.calls) == MAX_PLANNING_ATTEMPTS


async def test_recovers_after_one_correction() -> None:
    registry = await build_registry(_tool("git_status"))
    provider = StubProvider(
        [
            plan_call([{"id": "step_1", "description": "x", "tool": "nope"}]),
            plan_call([{"id": "step_1", "description": "x", "tool": "git_status"}]),
        ]
    )

    plan = await create_plan(provider, registry, "x", max_steps=10)

    assert plan.steps[0].tool == "git_status"
    assert len(provider.calls) == 2
    # The correction turn tells the model what was wrong.
    assert "rejected" in provider.calls[1][0][-1].content


# --- malformed plans -------------------------------------------------------


async def test_a_missing_objective_is_rejected() -> None:
    registry = await build_registry(_tool("git_status"))
    provider = StubProvider(
        [
            AIMessage(
                content="",
                tool_calls=[
                    {
                        "name": PLANNER_TOOL_NAME,
                        "args": {"steps": [{"id": "s", "description": "x", "tool": "git_status"}]},
                        "id": "c",
                        "type": "tool_call",
                    }
                ],
            )
        ] * MAX_PLANNING_ATTEMPTS
    )

    try:
        await create_plan(provider, registry, "x", max_steps=10)
        raise AssertionError("expected MissionPlanningError")
    except MissionPlanningError as exc:
        assert "objective" in exc.message


async def test_no_steps_is_rejected() -> None:
    registry = await build_registry(_tool("git_status"))
    provider = StubProvider([plan_call([])] * MAX_PLANNING_ATTEMPTS)

    try:
        await create_plan(provider, registry, "x", max_steps=10)
        raise AssertionError("expected MissionPlanningError")
    except MissionPlanningError as exc:
        assert "no steps" in exc.message


async def test_a_step_missing_an_id_is_rejected() -> None:
    registry = await build_registry(_tool("git_status"))
    provider = StubProvider(
        [plan_call([{"description": "x", "tool": "git_status"}])] * MAX_PLANNING_ATTEMPTS
    )

    try:
        await create_plan(provider, registry, "x", max_steps=10)
        raise AssertionError("expected MissionPlanningError")
    except MissionPlanningError as exc:
        assert "missing an id" in exc.message


# --- invalid arguments -----------------------------------------------------


async def test_arguments_the_tool_does_not_declare_are_rejected() -> None:
    registry = await build_registry(_tool("git_status", properties={"path": {}}))
    provider = StubProvider(
        [
            plan_call(
                [
                    {
                        "id": "step_1",
                        "description": "x",
                        "tool": "git_status",
                        "arguments": {"path": "~/p", "sudo": True},
                    }
                ]
            )
        ] * MAX_PLANNING_ATTEMPTS
    )

    try:
        await create_plan(provider, registry, "x", max_steps=10)
        raise AssertionError("expected MissionPlanningError")
    except MissionPlanningError as exc:
        assert "sudo" in exc.message


# --- duplicate steps and dependency cycles --------------------------------


async def test_duplicate_step_ids_are_rejected() -> None:
    registry = await build_registry(_tool("git_status"), _tool("read_file"))
    provider = StubProvider(
        [
            plan_call(
                [
                    {"id": "step_1", "description": "a", "tool": "git_status"},
                    {"id": "step_1", "description": "b", "tool": "read_file"},
                ]
            )
        ] * MAX_PLANNING_ATTEMPTS
    )

    try:
        await create_plan(provider, registry, "x", max_steps=10)
        raise AssertionError("expected MissionPlanningError")
    except MissionPlanningError as exc:
        assert "Duplicate step id" in exc.message


async def test_a_dependency_cycle_is_rejected() -> None:
    registry = await build_registry(_tool("git_status"), _tool("read_file"))
    provider = StubProvider(
        [
            plan_call(
                [
                    {
                        "id": "step_1", "description": "a", "tool": "git_status",
                        "depends_on": ["step_2"],
                    },
                    {
                        "id": "step_2", "description": "b", "tool": "read_file",
                        "depends_on": ["step_1"],
                    },
                ]
            )
        ] * MAX_PLANNING_ATTEMPTS
    )

    try:
        await create_plan(provider, registry, "x", max_steps=10)
        raise AssertionError("expected MissionPlanningError")
    except MissionPlanningError as exc:
        assert "loop" in exc.message


async def test_a_dangling_dependency_is_rejected() -> None:
    registry = await build_registry(_tool("git_status"))
    provider = StubProvider(
        [
            plan_call(
                [{"id": "step_1", "description": "a", "tool": "git_status", "depends_on": ["ghost"]}]
            )
        ] * MAX_PLANNING_ATTEMPTS
    )

    try:
        await create_plan(provider, registry, "x", max_steps=10)
        raise AssertionError("expected MissionPlanningError")
    except MissionPlanningError as exc:
        assert "unknown step" in exc.message


async def test_a_self_dependency_is_rejected() -> None:
    registry = await build_registry(_tool("git_status"))
    provider = StubProvider(
        [
            plan_call(
                [{"id": "step_1", "description": "a", "tool": "git_status", "depends_on": ["step_1"]}]
            )
        ] * MAX_PLANNING_ATTEMPTS
    )

    try:
        await create_plan(provider, registry, "x", max_steps=10)
        raise AssertionError("expected MissionPlanningError")
    except MissionPlanningError as exc:
        assert "itself" in exc.message


# --- plan-level safety limit ------------------------------------------------


async def test_a_plan_over_the_step_limit_is_rejected() -> None:
    registry = await build_registry(_tool("git_status"))
    steps = [
        {"id": f"step_{i}", "description": "x", "tool": "git_status"} for i in range(5)
    ]
    provider = StubProvider([plan_call(steps)])

    try:
        await create_plan(provider, registry, "x", max_steps=3)
        raise AssertionError("expected MissionPlanningError")
    except MissionPlanningError as exc:
        assert "step limit" in exc.message
    # Rejected outright — no retry consumed on a structurally valid plan
    # that simply asks for too much.
    assert len(provider.calls) == 1


async def test_an_invalid_run_if_is_rejected() -> None:
    registry = await build_registry(_tool("git_status"))
    provider = StubProvider(
        [
            plan_call(
                [{"id": "step_1", "description": "x", "tool": "git_status", "run_if": "maybe"}]
            )
        ] * MAX_PLANNING_ATTEMPTS
    )

    try:
        await create_plan(provider, registry, "x", max_steps=10)
        raise AssertionError("expected MissionPlanningError")
    except MissionPlanningError as exc:
        assert "run_if" in exc.message


async def test_the_model_declining_to_call_submit_plan_is_rejected() -> None:
    registry = await build_registry(_tool("git_status"))
    provider = StubProvider([AIMessage(content="I don't think a plan is needed.")] * MAX_PLANNING_ATTEMPTS)

    try:
        await create_plan(provider, registry, "x", max_steps=10)
        raise AssertionError("expected MissionPlanningError")
    except MissionPlanningError as exc:
        assert "expected form" in exc.message
