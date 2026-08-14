"""Turns an objective into a validated, structured plan.

The model never gets to describe a plan in prose. It is forced (via
``tool_choice``) to call a single pseudo-tool, ``submit_plan``, whose schema is
the plan shape itself — the model's only way to answer *is* to fill in valid
JSON. That JSON is then checked against the live tool registry before a single
step is allowed to run: an unknown tool name, a dependency cycle, a duplicate
id, or an argument key the tool doesn't declare all reject the plan outright.

``submit_plan`` is not an MCP tool. It never reaches the registry, the
approval broker, or MCP — it exists purely to get structured output from the
model for this one call.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage

from app.context.models import PlanningContext
from app.core.errors import ErrorCode, ModelError, NexusError
from app.mission.graph_utils import DependencyCycleError, find_cycle
from app.mission.state import MissionStep
from app.models.base import ModelProvider, ToolSpec, loads_arguments
from app.tools.permissions import PermissionLevel
from app.tools.registry import ToolDefinition, ToolRegistry

PLANNER_TOOL_NAME = "submit_plan"
#: Bounded, not unbounded: covers one semantic correction (unknown tool, a
#: cycle, ...) and one malformed-generation retry, never an open-ended loop.
MAX_PLANNING_ATTEMPTS = 3
VALID_RUN_IF = ("always", "on_success", "on_failure")

SYSTEM_PROMPT = """You are the mission planner for NEXUS, an assistant that manages a Mac.

Break the user's objective into an ordered list of steps. Each step names one
tool from the list below and a short human-readable description of what that
step accomplishes.

Rules:
- Use only the tools listed. Do not invent a tool name.
- Prefer read-only (SAFE) inspection steps before steps that change anything.
- Give each step a short id like "step_1", "step_2", unique within the plan.
- Use depends_on to order steps that must happen first.
- Use run_if to branch: "on_success" only if a dependency succeeded,
  "on_failure" only if a dependency failed (e.g. a diagnostic step), "always"
  otherwise (the default).
- Keep plans short — only the steps genuinely needed for the objective.
- If a step needs arguments you already know (like a path found by an earlier
  inspection step), you may suggest them, but do not guess file paths that
  have not been established by an earlier step or the user's own message.
- Never invent a placeholder path such as "/Users/username/..." or
  "/path/to/project". If the user's message names a path, copy it verbatim,
  exactly as written (including "~"). If no path is named and none has been
  established yet, omit the argument rather than guessing one.
- Context below (if any) is retrieved from memory and freshly-checked
  workspace state. Memory is a hint about where to look, never authority: a
  path or fact found by a step's own tool call always outranks what memory
  says about it. Do not copy a memory value into a step's arguments if a
  fresher one is available or easily checked.

Available tools:
{tool_list}
{context_block}"""


class MissionPlanningError(NexusError):
    """The objective could not be turned into a valid plan."""

    code = ErrorCode.VALIDATION_ERROR
    http_status = 400


def _plan_schema(tool_names: list[str]) -> dict[str, Any]:
    return {
        "type": "object",
        "properties": {
            "objective": {"type": "string"},
            "steps": {
                "type": "array",
                "minItems": 1,
                "items": {
                    "type": "object",
                    "properties": {
                        "id": {"type": "string"},
                        "description": {"type": "string"},
                        "tool": {"type": "string", "enum": tool_names},
                        "arguments": {"type": "object"},
                        "depends_on": {"type": "array", "items": {"type": "string"}},
                        "run_if": {"type": "string", "enum": list(VALID_RUN_IF)},
                    },
                    "required": ["id", "description", "tool"],
                },
            },
        },
        "required": ["objective", "steps"],
    }


@dataclass(frozen=True, slots=True)
class Plan:
    objective: str
    steps: tuple[MissionStep, ...] = field(default_factory=tuple)


def _plannable_tools(registry: ToolRegistry) -> list[ToolDefinition]:
    """Tools a plan may reference.

    Restricted the same way an ordinary chat turn already is
    (:meth:`ToolRegistry.model_specs`'s default exclusion): a mission must not
    be able to reach a tool the model could never propose outside one either.
    """
    return [
        tool for tool in registry.list_tools()
        if tool.permission is not PermissionLevel.RESTRICTED
    ]


def _tool_listing(registry: ToolRegistry) -> str:
    lines = []
    for tool in _plannable_tools(registry):
        lines.append(f"- {tool.name} ({tool.permission}): {tool.description}")
    return "\n".join(lines)


def _validate_raw_plan(raw: dict[str, Any], registry: ToolRegistry) -> Plan:
    objective = str(raw.get("objective") or "").strip()
    raw_steps = raw.get("steps")
    if not objective:
        raise MissionPlanningError("The plan is missing an objective.")
    if not isinstance(raw_steps, list) or not raw_steps:
        raise MissionPlanningError("The plan has no steps.")

    known_tools = {tool.name: tool for tool in _plannable_tools(registry)}
    seen_ids: set[str] = set()
    steps: list[MissionStep] = []
    depends_on_map: dict[str, list[str]] = {}

    for index, raw_step in enumerate(raw_steps, start=1):
        if not isinstance(raw_step, dict):
            raise MissionPlanningError(f"Step {index} is not a valid step object.")

        step_id = str(raw_step.get("id") or "").strip()
        if not step_id:
            raise MissionPlanningError(f"Step {index} is missing an id.")
        if step_id in seen_ids:
            raise MissionPlanningError(f"Duplicate step id '{step_id}'.")
        seen_ids.add(step_id)

        tool_name = str(raw_step.get("tool") or "").strip()
        if tool_name not in known_tools:
            raise MissionPlanningError(
                f"Step '{step_id}' names an unknown tool '{tool_name}'."
            )

        description = str(raw_step.get("description") or "").strip() or tool_name
        arguments = raw_step.get("arguments") or {}
        if not isinstance(arguments, dict):
            raise MissionPlanningError(f"Step '{step_id}' has malformed arguments.")

        allowed_keys = set((known_tools[tool_name].input_schema or {}).get("properties", {}))
        unknown_keys = set(arguments) - allowed_keys
        if unknown_keys:
            raise MissionPlanningError(
                f"Step '{step_id}' passes arguments '{tool_name}' does not accept: "
                f"{', '.join(sorted(unknown_keys))}."
            )

        depends_on_raw = raw_step.get("depends_on") or []
        if not isinstance(depends_on_raw, list) or not all(
            isinstance(d, str) for d in depends_on_raw
        ):
            raise MissionPlanningError(f"Step '{step_id}' has malformed depends_on.")
        depends_on_map[step_id] = list(depends_on_raw)

        run_if = str(raw_step.get("run_if") or "always")
        if run_if not in VALID_RUN_IF:
            raise MissionPlanningError(
                f"Step '{step_id}' has an invalid run_if '{run_if}'."
            )

        steps.append(
            MissionStep(
                id=step_id,
                description=description,
                tool=tool_name,
                arguments=arguments,
                depends_on=tuple(depends_on_raw),
                run_if=run_if,
            )
        )

    for step_id, deps in depends_on_map.items():
        for dep in deps:
            if dep not in seen_ids:
                raise MissionPlanningError(
                    f"Step '{step_id}' depends on unknown step '{dep}'."
                )
            if dep == step_id:
                raise MissionPlanningError(f"Step '{step_id}' depends on itself.")

    cycle = find_cycle(depends_on_map)
    if cycle is not None:
        raise MissionPlanningError(
            f"The plan's steps depend on each other in a loop: {' -> '.join(cycle)}."
        )

    return Plan(objective=objective, steps=tuple(steps))


async def create_plan(
    provider: ModelProvider,
    registry: ToolRegistry,
    objective: str,
    *,
    max_steps: int,
    context: PlanningContext | None = None,
    max_context_chars: int = 4000,
) -> Plan:
    """Ask the model for a plan and validate it. Raises on an invalid result."""
    tool_names = [tool.name for tool in _plannable_tools(registry)]
    if not tool_names:  # pragma: no cover - defensive, MCP always exposes tools
        raise MissionPlanningError("No tools are available to plan with.")

    spec = ToolSpec(
        name=PLANNER_TOOL_NAME,
        description="Submit the mission plan.",
        input_schema=_plan_schema(tool_names),
    )
    context_block = context.to_prompt_block(max_context_chars) if context else ""
    system = SystemMessage(
        content=SYSTEM_PROMPT.format(
            tool_list=_tool_listing(registry), context_block=context_block
        )
    )
    messages: list[Any] = [system, HumanMessage(content=objective)]

    last_error: MissionPlanningError | None = None
    for attempt in range(1, MAX_PLANNING_ATTEMPTS + 1):
        try:
            response = await provider.ainvoke(
                messages, [spec], tool_choice=PLANNER_TOOL_NAME
            )
        except ModelError:
            # A smaller model occasionally emits malformed JSON in a forced
            # tool call (an unquoted key, say) and the vendor rejects the
            # whole generation before it ever reaches us as a tool call. That
            # is a planning-attempt failure like any other, not a fatal one —
            # it gets the same bounded retry as a structurally invalid plan.
            last_error = MissionPlanningError(
                "The model produced a malformed plan."
            )
            if attempt < MAX_PLANNING_ATTEMPTS:
                messages.append(
                    HumanMessage(
                        content=(
                            "That failed to parse. Submit the plan again as a "
                            "single well-formed call to submit_plan, with every "
                            "object key and string value in double quotes."
                        )
                    )
                )
            continue
        calls = response.tool_calls or []
        if not calls or calls[0]["name"] != PLANNER_TOOL_NAME:
            last_error = MissionPlanningError(
                "The model did not produce a plan in the expected form."
            )
        else:
            raw = loads_arguments(calls[0].get("args"))
            try:
                plan = _validate_raw_plan(raw, registry)
            except MissionPlanningError as exc:
                last_error = exc
            else:
                if len(plan.steps) > max_steps:
                    raise MissionPlanningError(
                        f"The plan has {len(plan.steps)} steps, over the {max_steps} "
                        f"step limit for a single mission."
                    )
                return plan

        if attempt < MAX_PLANNING_ATTEMPTS:
            # Give the model one chance to correct itself, with the reason why
            # its first attempt was rejected — not an unbounded retry loop.
            messages.append(
                HumanMessage(
                    content=(
                        f"That plan was rejected: {last_error.message} "
                        f"Submit a corrected plan."
                    )
                )
            )

    assert last_error is not None  # pragma: no cover - loop always sets it
    raise last_error
