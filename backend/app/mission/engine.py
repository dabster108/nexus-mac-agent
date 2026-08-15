"""The mission engine.

This module does not add a security layer — it orchestrates the one that
already exists. Every step becomes an ordinary single-task run of the exact
same graph normal chat messages use (:func:`app.agent.graph.build_agent_graph`):
same tool registry, same :class:`~app.tools.permissions.PermissionPolicy`, same
:class:`~app.agent.approvals.ApprovalBroker`. A CONFIRM step blocks exactly the
way a CONFIRM tool always has — inside ``tool_node``'s ``await broker.wait(...)``
— which is what lets "pause for approval, resume after" fall out of the
existing machinery instead of needing a new pause/resume state machine here.

    Mission
      -> Planner (validated against the live tool registry)
      -> Step (one at a time, respecting depends_on / run_if)
          -> ordinary single-task Task (its own TaskRecord, its own graph run)
              -> agent_node / tool_node (unchanged)
                  -> PermissionPolicy -> ApprovalBroker -> MCP
      -> Mission summary
"""

from __future__ import annotations

import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Any

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

from app.agent import events as ev
from app.agent.approvals import ApprovalBroker
from app.agent.events import EventSink, EventType
from app.agent.graph import build_agent_graph
from app.agent.state import initial_state
from app.agent.tasks import TaskRecord, TaskStore
from app.context.intent import MISSION_PLAN
from app.context.memory_events import emit_memory_outcome_events
from app.context.models import ContextBudget
from app.core.errors import ErrorCode
from app.core.logging import get_logger
from app.mission.planner import MissionPlanningError, create_plan
from app.mission.state import Mission, MissionStatus, MissionStep, StepStatus
from app.mission.store import InMemoryMissionStore
from app.models.base import ModelProvider, content_to_text
from app.tools.permissions import PermissionLevel, PermissionPolicy
from app.tools.registry import ToolDefinition, ToolRegistry, ToolResult

logger = get_logger(__name__)


def _observe_mission(
    task_id: str, objective: str, status: str, reason: str | None
) -> None:
    """Record a mission's ending as an observation.

    Best-effort and lazily imported, like the runner's equivalent: a mission's
    result must not depend on whether anything was watching.
    """
    try:
        from app.observations import rules
        from app.observations.store import get_observation_store

        observation = rules.mission_outcome(task_id, objective, status, reason)
        if observation:
            get_observation_store().record(observation)
    except Exception:  # noqa: BLE001 - observation must not affect the mission
        logger.warning("Could not record a mission observation", exc_info=True)

#: A single mission step is "call one tool, read the result, summarise" — a
#: much smaller budget than an ordinary chat turn needs, and small enough that
#: a step cannot itself spiral into an open-ended tool-calling loop.
STEP_MAX_ITERATIONS = 4

#: Context keys carried between steps when a tool's structured result exposes
#: them. Deliberately small and generic rather than a general memory system —
#: enough for "step 2 should look at the directory step 1 found."
_CONTEXT_KEYS = ("path", "process_id", "url", "port")

TaskFactory = Callable[[str], TaskRecord]
SinkFactory = Callable[[TaskRecord], EventSink]
Finaliser = Callable[[TaskRecord, dict[str, Any]], TaskRecord]


@dataclass(frozen=True, slots=True)
class MissionLimits:
    max_steps: int
    max_retries_per_step: int
    max_tool_calls: int
    max_runtime_seconds: float

    @property
    def max_loop_iterations(self) -> int:
        # Defense in depth beyond the per-step retry bound: the step loop
        # cannot run forever even if every other limit were somehow bypassed.
        return self.max_steps * (self.max_retries_per_step + 1) + 10


class _SingleToolSource:
    """Restricts a step's model to exactly one tool, delegating execution to
    the real registry. Not a new tool backend — a narrow view of one."""

    def __init__(self, definition: ToolDefinition, parent: ToolRegistry) -> None:
        self._definition = definition
        self._parent = parent

    @property
    def name(self) -> str:
        return self._definition.source

    async def list_tools(self) -> Sequence[ToolDefinition]:
        return (self._definition,)

    async def call_tool(self, name: str, arguments: dict[str, Any]) -> ToolResult:
        return await self._parent.call(name, arguments)


def _final_answer(messages: Sequence[Any]) -> str | None:
    for message in reversed(list(messages)):
        if isinstance(message, AIMessage):
            text = content_to_text(message.content).strip()
            if text:
                return text
    return None


def _extract_context(value: Any, into: dict[str, Any]) -> None:
    """Pull well-known fields out of a tool's structured result, if present."""
    if isinstance(value, dict):
        for key in _CONTEXT_KEYS:
            if key in value and value[key] is not None:
                into[key] = value[key]


def _step_outcome(step: MissionStep, final_state: dict[str, Any]) -> tuple[StepStatus, str]:
    """What a step's underlying task run means for the mission.

    A tool that ran and *reported* failure (a test suite with failing tests,
    say) is not a step failure — the step's job was to find that out, and it
    did. A step only fails here when it could not be carried out at all: a
    graph-level error, an unresolved approval, or the target tool itself being
    refused, denied, or erroring.
    """
    error = final_state.get("error")
    if error:
        return StepStatus.FAILED, str(error.get("message") or "The step failed.")

    if final_state.get("requires_permission"):  # pragma: no cover - defensive
        request = final_state.get("permission_request") or {}
        return StepStatus.FAILED, str(request.get("reason") or "Approval was not resolved.")

    tool_results = final_state.get("tool_results") or []
    target_results = [r for r in tool_results if r.get("name") == step.tool]
    if target_results and not target_results[-1].get("success", False):
        return StepStatus.FAILED, str(target_results[-1].get("content") or "The tool did not run.")

    message = _final_answer(final_state.get("messages") or []) or "Step finished."
    return StepStatus.COMPLETED, message


def _run_if_eligible(mission: Mission, step: MissionStep) -> tuple[bool, str]:
    """Whether a step's run_if condition is met, given its dependencies' outcomes."""
    deps = [mission.step(dep_id) for dep_id in step.depends_on]
    if any(dep.status is StepStatus.CANCELLED for dep in deps):
        return False, "a dependency was cancelled"
    if step.run_if == "on_success":
        if all(dep.status is StepStatus.COMPLETED for dep in deps):
            return True, ""
        return False, "a dependency did not complete successfully"
    if step.run_if == "on_failure":
        if deps and any(dep.status is StepStatus.FAILED for dep in deps):
            return True, ""
        return False, "no dependency failed"
    return True, ""


def _mission_outcome(mission: Mission) -> tuple[MissionStatus, str | None]:
    """COMPLETED unless a step failed with nothing downstream to recover it."""
    unhandled = [
        step.id
        for step in mission.steps
        if step.status is StepStatus.FAILED
        and not any(
            other.run_if == "on_failure"
            and step.id in other.depends_on
            and other.status is StepStatus.COMPLETED
            for other in mission.steps
        )
    ]
    if unhandled:
        return (
            MissionStatus.FAILED,
            f"Step(s) failed without a recovery step: {', '.join(unhandled)}.",
        )
    return MissionStatus.COMPLETED, None


class MissionEngine:
    """Runs one mission to completion, respecting every existing safety control."""

    def __init__(
        self,
        *,
        task_store: TaskStore,
        broker: ApprovalBroker,
        mission_store: InMemoryMissionStore,
        create_task: TaskFactory,
        sink_for: SinkFactory,
        finalise: Finaliser,
        request_timeout_seconds: float,
        permission_timeout_seconds: float,
        limits: MissionLimits,
        context_budget: ContextBudget,
    ) -> None:
        self._tasks = task_store
        self._broker = broker
        self._missions = mission_store
        self._create_task = create_task
        self._sink_for = sink_for
        self._finalise = finalise
        self._request_timeout = request_timeout_seconds
        self._permission_timeout = permission_timeout_seconds
        self._limits = limits
        self._context_budget = context_budget

    async def run(
        self,
        mission: Mission,
        *,
        mission_record: TaskRecord,
        provider: ModelProvider,
        registry: ToolRegistry,
        policy: PermissionPolicy,
    ) -> dict[str, Any]:
        """Run the mission to a terminal state and return a ``_finalise``-shaped dict."""
        self._missions.add(mission)
        mission_emit = self._sink_for(mission_record)
        mission_emit(ev.mission_started(mission.task_id, mission.id, mission.objective))

        # Imported here rather than at module scope: the collector imports
        # `app.agent` for the event vocabulary, `app.agent` imports the runner,
        # and the runner imports this package — a cycle that fires whenever
        # `app.context` happens to be imported before `app.agent`.
        from app.context.collector import ContextCollector

        collector = ContextCollector(
            registry,
            max_memories=self._context_budget.max_memories,
            max_workspace_facts=self._context_budget.max_workspace_facts,
            budget=self._context_budget,
        )
        context = await collector.collect(
            mission.objective, mission.task_id, mission_emit, plan=MISSION_PLAN
        )
        # Seed from context, not authority: a step's own fresh tool result
        # (via _extract_context, below) always overwrites these as it arrives.
        for workspace in context.workspaces:
            if workspace.verified:
                mission.context.setdefault("path", workspace.path)
        for memory in context.memories:
            for key in ("path", "process_id", "url", "port"):
                if key in memory.value and not memory.stale:
                    mission.context.setdefault(key, memory.value[key])

        try:
            plan = await create_plan(
                provider, registry, mission.objective,
                max_steps=self._limits.max_steps,
                context=context,
                max_context_chars=self._context_budget.max_chars,
            )
        except MissionPlanningError as exc:
            return self._fail_mission(mission, mission_record, mission_emit, exc.message)

        mission.steps = list(plan.steps)
        mission.status = MissionStatus.RUNNING
        mission_emit(
            ev.mission_plan_created(
                mission.task_id,
                mission.id,
                [step.to_public_dict() for step in mission.steps],
            )
        )
        logger.info(
            "Mission plan: %d step(s) for %r", len(mission.steps), mission.objective,
            extra={"task_id": mission.task_id},
        )

        started_at = time.monotonic()
        iterations = 0
        while True:
            iterations += 1
            if iterations > self._limits.max_loop_iterations:
                return self._fail_mission(
                    mission, mission_record, mission_emit,
                    "safety_limit_reached: max_loop_iterations",
                )
            elapsed = time.monotonic() - started_at
            if elapsed > self._limits.max_runtime_seconds:
                return self._fail_mission(
                    mission, mission_record, mission_emit,
                    f"safety_limit_reached: max_runtime "
                    f"({self._limits.max_runtime_seconds:g}s)",
                )
            if mission.tool_call_count > self._limits.max_tool_calls:
                return self._fail_mission(
                    mission, mission_record, mission_emit,
                    f"safety_limit_reached: max_tool_calls "
                    f"({self._limits.max_tool_calls})",
                )

            step = self._next_step(mission)
            if step is None:
                break  # every step is terminal

            eligible, skip_reason = _run_if_eligible(mission, step)
            if not eligible:
                step.status = StepStatus.SKIPPED
                step.result_message = skip_reason
                mission_emit(
                    ev.mission_step_skipped(mission.task_id, mission.id, step.id, skip_reason)
                )
                continue

            await self._run_step(
                mission, step, mission_record, mission_emit,
                provider=provider, registry=registry, policy=policy,
            )

        status, reason = _mission_outcome(mission)
        mission.status = status
        mission.failure_reason = reason
        summary = mission.summary()

        _observe_mission(mission.task_id, mission.objective, str(status).lower(), reason)

        if status is MissionStatus.FAILED:
            mission_emit(ev.mission_failed(mission.task_id, mission.id, reason or "", summary))
            mission_emit(ev.task_error(mission.task_id, str(ErrorCode.VALIDATION_ERROR), reason or "The mission failed."))
            return {
                "error": {"code": str(ErrorCode.VALIDATION_ERROR), "message": reason or "The mission failed."},
                "requires_permission": False,
                "permission_request": None,
                "messages": [],
            }

        mission_emit(ev.mission_completed(mission.task_id, mission.id, summary))
        wrapup = await self._summarise(provider, mission)
        return {
            "error": None,
            "requires_permission": False,
            "permission_request": None,
            "messages": [AIMessage(content=wrapup)],
        }

    def _next_step(self, mission: Mission) -> MissionStep | None:
        for step in mission.steps:
            if step.status is StepStatus.PENDING:
                deps = [mission.step(dep_id) for dep_id in step.depends_on]
                if all(dep.status.is_terminal for dep in deps):
                    return step
        return None

    async def _run_step(
        self,
        mission: Mission,
        step: MissionStep,
        mission_record: TaskRecord,
        mission_emit: EventSink,
        *,
        provider: ModelProvider,
        registry: ToolRegistry,
        policy: PermissionPolicy,
    ) -> None:
        step.status = StepStatus.RUNNING
        mission_emit(ev.mission_step_started(mission.task_id, mission.id, step.id, step.description))

        definition = registry.get(step.tool)
        if definition is None:  # pragma: no cover - planner already validated this
            step.status = StepStatus.FAILED
            step.result_message = f"'{step.tool}' is no longer available."
            mission_emit(
                ev.mission_step_failed(mission.task_id, mission.id, step.id, step.result_message)
            )
            return

        step_record = self._create_task(f"[{mission.id}] {step.description}")
        step.task_id = step_record.task_id
        step_sink = self._wrap_sink(mission, step, mission_record, mission_emit, step_record)

        scoped = ToolRegistry([_SingleToolSource(definition, registry)])
        await scoped.refresh()

        graph = build_agent_graph(
            provider=provider,
            registry=scoped,
            policy=policy,
            broker=self._broker,
            emit=step_sink,
            max_iterations=STEP_MAX_ITERATIONS,
            timeout=self._request_timeout,
            permission_timeout=self._permission_timeout,
        )

        instruction = self._instruction_for(mission, step)
        final_state: dict[str, Any] = {}
        async for chunk in graph.astream(initial_state(step_record.task_id, instruction), stream_mode="values"):
            final_state = chunk

        mission.tool_call_count += len(final_state.get("tool_results") or [])
        for result in final_state.get("tool_results") or []:
            _extract_context(result.get("structured"), mission.context)
        emit_memory_outcome_events(
            final_state.get("tool_results") or [], step_record.task_id, step_sink
        )

        status, message = _step_outcome(step, final_state)
        self._finalise(step_record, final_state)

        if status is StepStatus.COMPLETED:
            step.status = StepStatus.COMPLETED
            step.result_message = message
            mission_emit(ev.mission_step_completed(mission.task_id, mission.id, step.id, message))
            return

        # Failed: SAFE tools may retry (bounded); CONFIRM tools never auto-retry
        # — repeatedly re-asking for approval is exactly the loop #15 forbids.
        can_retry = (
            definition.permission is PermissionLevel.SAFE
            and step.retries < self._limits.max_retries_per_step
        )
        if can_retry:
            step.retries += 1
            step.status = StepStatus.PENDING
            mission_emit(
                ev.mission_step_failed(
                    mission.task_id, mission.id, step.id,
                    f"{message} (retry {step.retries}/{self._limits.max_retries_per_step})",
                )
            )
            return

        step.status = StepStatus.FAILED
        step.result_message = message
        mission_emit(ev.mission_step_failed(mission.task_id, mission.id, step.id, message))

    def _wrap_sink(
        self,
        mission: Mission,
        step: MissionStep,
        mission_record: TaskRecord,
        mission_emit: EventSink,
        step_record: TaskRecord,
    ) -> EventSink:
        """Mirror a step's events onto the mission's own stream.

        A client watching only the mission's task_id must see everything —
        tool_started, permission_required, all of it — without knowing the
        step's task_id in advance. The step's own record still gets every
        event too, via the base sink, so ``GET /api/tasks/{step_task_id}``
        keeps working exactly like an ordinary task.
        """
        base = self._sink_for(step_record)

        def emit(event: ev.ExecutionEvent) -> None:
            base(event)
            mission_emit(event)
            if event.type is EventType.PERMISSION_REQUIRED:
                step.status = StepStatus.WAITING_APPROVAL
                request_id = event.data.get("request_id", "")
                # Published directly, not through mission_emit: that sink's
                # "the next event after PERMISSION_REQUIRED means we resumed"
                # heuristic would otherwise read this synthetic follow-up event
                # as the resumption and flip the mission back to RUNNING before
                # the wait has even begun.
                self._tasks.publish(
                    mission_record,
                    [
                        ev.mission_waiting_approval(
                            mission.task_id, mission.id, step.id, request_id,
                            event.message or "Approval is required.",
                        )
                    ],
                )

        return emit

    def _instruction_for(self, mission: Mission, step: MissionStep) -> str:
        # The objective is quoted first and labelled as the source of truth for
        # any path it names — the plan's own "suggested" arguments are a hint
        # from an earlier, separate model call, not something to trust blindly
        # over what the user actually wrote.
        lines = [
            f'Mission objective (verbatim from the user): "{mission.objective}"',
            f"Current step: {step.description}",
            f"Use the tool '{step.tool}' to complete this step if it applies.",
        ]
        if step.arguments:
            lines.append(
                f"The plan suggests these arguments: {step.arguments}. Use them only "
                f"if they match what the objective or known context actually say — "
                f"never a placeholder path like '/Users/username/...'. If a path is "
                f"named in the objective above, use that exact path instead."
            )
        if mission.context:
            known = ", ".join(f"{key}={value}" for key, value in mission.context.items())
            lines.append(f"Known context from earlier steps: {known}.")
        return "\n".join(lines)

    async def _summarise(self, provider: ModelProvider, mission: Mission) -> str:
        """A short natural-language wrap-up, from the mission's own results."""
        lines = [f"Objective: {mission.objective}", "Results:"]
        for step in mission.steps:
            lines.append(f"- [{step.status}] {step.description}: {step.result_message or ''}")
        try:
            response = await provider.ainvoke(
                [
                    SystemMessage(
                        content=(
                            "Summarise this completed mission for the user in 2-4 "
                            "concise sentences. Do not list internal step ids or "
                            "mention that you are an AI."
                        )
                    ),
                    HumanMessage(content="\n".join(lines)),
                ]
            )
            text = content_to_text(response.content).strip()
            if text:
                return text
        except Exception:  # noqa: BLE001 - the structured summary is the fallback
            logger.warning("Mission summary call failed; using the structured summary")
        return "Mission completed. " + "; ".join(
            f"{step.description}: {step.result_message}"
            for step in mission.steps
            if step.status is not StepStatus.SKIPPED
        )

    def _fail_mission(
        self,
        mission: Mission,
        mission_record: TaskRecord,
        mission_emit: EventSink,
        reason: str,
    ) -> dict[str, Any]:
        mission.status = MissionStatus.FAILED
        mission.failure_reason = reason
        summary = mission.summary()
        mission_emit(ev.mission_failed(mission.task_id, mission.id, reason, summary))
        mission_emit(ev.task_error(mission.task_id, str(ErrorCode.VALIDATION_ERROR), reason))
        logger.info("Mission failed: %s", reason, extra={"task_id": mission.task_id})
        return {
            "error": {"code": str(ErrorCode.VALIDATION_ERROR), "message": reason},
            "requires_permission": False,
            "permission_request": None,
            "messages": [],
        }

    def cancel(self, mission: Mission) -> None:
        """Mark every non-terminal step cancelled and free any pending approval.

        Called from the outer CancelledError handler. Does not stop anything a
        step already started successfully (a running dev server, say) — no
        automatic rollback of completed actions.
        """
        mission.status = MissionStatus.CANCELLED
        for step in mission.steps:
            if not step.status.is_terminal:
                if step.task_id:
                    self._broker.cancel_for_task(step.task_id)
                step.status = StepStatus.CANCELLED
