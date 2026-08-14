"""Agent runner.

Owns one execution of the graph: opens the MCP sessions, builds the tool
registry, runs the graph, streams events into the task store, and turns the
final state into a task record. FastAPI routes call this and nothing deeper.

Tools come from the shared MCP session pool the application opens at startup,
so servers holding state — a supervised development server, say — outlive any
one request. When no pool is open the runner falls back to a session scoped to
the run, opened and closed within the single task the stdio transport requires.
"""

from __future__ import annotations

import asyncio
from collections.abc import Sequence
from contextlib import AsyncExitStack
from functools import lru_cache
from typing import Any

from langchain_core.messages import AIMessage

from app.agent import events as ev
from app.agent.approvals import ApprovalBroker, get_approval_broker
from app.agent.events import EventSink
from app.agent.graph import build_agent_graph
from app.agent.state import initial_state
from app.agent.tasks import TaskRecord, TaskStatus, TaskStore, get_task_store
from app.context.memory_events import (
    MEMORY_CONFIRM_TOOLS,
    describe_proposal,
    emit_memory_outcome_events,
)
from app.context.models import ContextBudget
from app.core.config import Settings, get_settings
from app.core.errors import NexusError, ValidationError
from app.core.logging import get_logger
from app.mcp.registry import MCPServerRegistry, MCPSessionPool, get_mcp_pool
from app.mission.detection import looks_like_mission
from app.mission.engine import MissionEngine, MissionLimits
from app.mission.state import Mission, new_mission_id
from app.mission.store import InMemoryMissionStore, get_mission_store
from app.models.base import content_to_text
from app.models.router import ModelRouter, get_model_router
from app.tools.permissions import PermissionPolicy
from app.tools.registry import ToolDefinition, ToolRegistry

logger = get_logger(__name__)

NO_ANSWER = "The agent finished without producing an answer."
CANCELLED_MESSAGE = "The task was cancelled."


def _final_answer(messages: Sequence[Any]) -> str | None:
    """The last thing the assistant actually said."""
    for message in reversed(list(messages)):
        if isinstance(message, AIMessage):
            text = content_to_text(message.content).strip()
            if text:
                return text
    return None


class AgentRunner:
    def __init__(
        self,
        *,
        settings: Settings | None = None,
        router: ModelRouter | None = None,
        task_store: TaskStore | None = None,
        server_registry: MCPServerRegistry | None = None,
        broker: ApprovalBroker | None = None,
        pool: MCPSessionPool | None = None,
        mission_store: InMemoryMissionStore | None = None,
    ) -> None:
        self._settings = settings or get_settings()
        self._router = router or get_model_router()
        self._tasks = task_store or get_task_store()
        self._servers = server_registry or MCPServerRegistry.from_settings(self._settings)
        self._broker = broker or get_approval_broker()
        # Only used when the application has opened it; tests leave it closed.
        self._pool = pool if pool is not None else get_mcp_pool()
        self._missions = mission_store or get_mission_store()

    @property
    def task_store(self) -> TaskStore:
        return self._tasks

    @property
    def approval_broker(self) -> ApprovalBroker:
        return self._broker

    async def _open_registry(self, stack: AsyncExitStack) -> ToolRegistry:
        """Tools for this run, from the shared session pool where there is one.

        The pool keeps servers alive between requests, which is what lets a
        development server started by one message still be there for the next.
        Without an open pool — in tests, or if a server was unavailable at
        startup — this falls back to a session scoped to the run.
        """
        pool = self._pool
        if pool is not None and pool.is_open:
            registry = ToolRegistry(pool.sources)
            await registry.refresh()
            return registry

        sources = await self._servers.open_sources(stack)
        registry = ToolRegistry(sources)
        await registry.refresh()
        return registry

    async def list_tools(self) -> list[ToolDefinition]:
        """Discover the currently available tools (used by ``GET /api/tools``)."""
        async with AsyncExitStack() as stack:
            registry = await self._open_registry(stack)
            return registry.list_tools()
        return []  # pragma: no cover - unreachable, satisfies type checkers

    def start(
        self,
        message: str,
        *,
        provider: str | None = None,
        approved_tools: Sequence[str] = (),
    ) -> TaskRecord:
        """Accept a request and run it in the background.

        Returns as soon as the task exists; progress arrives over ``WS /api/ws``
        or via ``GET /api/tasks/{task_id}``.
        """
        record = self._create_record(message)
        handle = asyncio.create_task(
            self._run_record(record, provider=provider, approved_tools=approved_tools),
            name=f"nexus-{record.task_id}",
        )
        self._tasks.register_run(record.task_id, handle)
        return record

    async def cancel(self, task_id: str) -> TaskRecord:
        """Stop a running task. A finished task is returned untouched."""
        record = self._tasks.require(task_id)
        if record.status.is_terminal:
            return record

        # Free anything the run is blocked on before cancelling it.
        self._broker.cancel_for_task(task_id)
        self._tasks.request_cancel(task_id)

        # Give the run a moment to unwind and mark itself cancelled.
        for _ in range(50):
            if record.status.is_terminal:
                return record
            await asyncio.sleep(0.01)

        # It never registered a handle (or never started); mark it here.
        return self._mark_cancelled(record)

    def _mark_cancelled(self, record: TaskRecord) -> TaskRecord:
        if record.status.is_terminal:
            return record
        self._tasks.publish(record, [ev.task_cancelled(record.task_id)])
        logger.info("TASK CANCELLED", extra={"task_id": record.task_id})
        return self._tasks.finish(
            record, status=TaskStatus.CANCELLED, response=CANCELLED_MESSAGE
        )

    def _create_record(self, message: str) -> TaskRecord:
        text = (message or "").strip()
        if not text:
            raise ValidationError("The message cannot be empty.")
        record = self._tasks.create(text)
        logger.info("TASK START", extra={"task_id": record.task_id})
        self._tasks.publish(record, [ev.task_started(record.task_id, text)])
        return record

    async def run(
        self,
        message: str,
        *,
        provider: str | None = None,
        approved_tools: Sequence[str] = (),
    ) -> TaskRecord:
        """Execute one user request end to end, awaiting the result."""
        record = self._create_record(message)
        return await self._run_record(
            record, provider=provider, approved_tools=approved_tools
        )

    async def _run_record(
        self,
        record: TaskRecord,
        *,
        provider: str | None,
        approved_tools: Sequence[str],
    ) -> TaskRecord:
        task_id = record.task_id
        text = record.request

        try:
            if looks_like_mission(text):
                final_state = await self._execute_mission(
                    task_id, text, provider, approved_tools, record
                )
            else:
                final_state = await self._execute(task_id, text, provider, approved_tools, record)
        except asyncio.CancelledError:
            self._broker.cancel_for_task(task_id)
            self._mark_cancelled(record)
            raise
        except NexusError as exc:
            logger.error(
                "TASK ERROR: %s (%s)", exc.message, exc.detail or "no detail",
                extra={"task_id": task_id},
            )
            self._tasks.publish(record, [ev.task_error(task_id, str(exc.code), exc.message)])
            return self._tasks.finish(
                record,
                status=TaskStatus.ERROR,
                response=exc.message,
                error={"code": str(exc.code), "message": exc.message},
            )
        except Exception as exc:  # noqa: BLE001 - never fail silently
            wrapped = NexusError(
                "The agent hit an unexpected problem.",
                detail=f"{type(exc).__name__}: {exc}",
            )
            logger.exception("TASK ERROR (unhandled)", extra={"task_id": task_id})
            self._tasks.publish(
                record, [ev.task_error(task_id, str(wrapped.code), wrapped.message)]
            )
            return self._tasks.finish(
                record,
                status=TaskStatus.ERROR,
                response=wrapped.message,
                error={"code": str(wrapped.code), "message": wrapped.message},
            )

        return self._finalise(record, final_state)

    async def _execute(
        self,
        task_id: str,
        text: str,
        provider: str | None,
        approved_tools: Sequence[str],
        record: TaskRecord,
    ) -> dict[str, Any]:
        model_provider = self._router.get_provider(provider)
        policy = PermissionPolicy(approved_tools)

        async with AsyncExitStack() as stack:
            registry = await self._open_registry(stack)
            emit = self._sink_for(record)
            graph = build_agent_graph(
                provider=model_provider,
                registry=registry,
                policy=policy,
                broker=self._broker,
                emit=emit,
                max_iterations=self._settings.agent_max_iterations,
                timeout=self._settings.request_timeout_seconds,
                permission_timeout=self._settings.permission_timeout_seconds,
            )

            final_state: dict[str, Any] = {}
            # Events are delivered by the sink as they happen, so only the final
            # state is taken from the stream — publishing here too would double
            # every event.
            async for chunk in graph.astream(
                initial_state(task_id, text), stream_mode="values"
            ):
                final_state = chunk
            emit_memory_outcome_events(final_state.get("tool_results") or [], task_id, emit)
            return final_state

        return {}  # pragma: no cover - unreachable, satisfies type checkers

    async def _execute_mission(
        self,
        task_id: str,
        text: str,
        provider: str | None,
        approved_tools: Sequence[str],
        record: TaskRecord,
    ) -> dict[str, Any]:
        """Run ``text`` as a multi-step mission instead of a single tool turn.

        Reuses everything ``_execute`` does — the same provider, registry,
        permission policy and approval broker — through
        :class:`~app.mission.engine.MissionEngine`, which is the only place
        mission-specific orchestration lives. This method's job is just to
        assemble the engine's dependencies from what the runner already has.
        """
        model_provider = self._router.get_provider(provider)
        policy = PermissionPolicy(approved_tools)

        async with AsyncExitStack() as stack:
            registry = await self._open_registry(stack)
            mission = Mission(id=new_mission_id(), objective=text, task_id=task_id)
            engine = MissionEngine(
                task_store=self._tasks,
                broker=self._broker,
                mission_store=self._missions,
                create_task=self._create_record,
                sink_for=self._sink_for,
                finalise=self._finalise,
                request_timeout_seconds=self._settings.request_timeout_seconds,
                permission_timeout_seconds=self._settings.permission_timeout_seconds,
                limits=MissionLimits(
                    max_steps=self._settings.mission_max_steps,
                    max_retries_per_step=self._settings.mission_max_retries_per_step,
                    max_tool_calls=self._settings.mission_max_tool_calls,
                    max_runtime_seconds=self._settings.mission_max_runtime_seconds,
                ),
                context_budget=ContextBudget(
                    max_memories=self._settings.context_max_memories,
                    max_workspace_facts=self._settings.context_max_workspace_facts,
                    max_chars=self._settings.context_max_chars,
                ),
            )
            try:
                return await engine.run(
                    mission,
                    mission_record=record,
                    provider=model_provider,
                    registry=registry,
                    policy=policy,
                )
            except asyncio.CancelledError:
                # Mission-specific cleanup (mark steps cancelled, free any
                # pending approval) before the outer handler cancels the task.
                engine.cancel(mission)
                self._tasks.publish(record, [ev.mission_cancelled(task_id, mission.id)])
                raise

        return {}  # pragma: no cover - unreachable, satisfies type checkers

    def _sink_for(self, record: TaskRecord) -> EventSink:
        """Publish events live and keep the task's status in step with them."""

        def emit(event: ev.ExecutionEvent) -> None:
            self._tasks.publish(record, [event])
            if event.type is ev.EventType.PERMISSION_REQUIRED:
                self._tasks.note_status(record, TaskStatus.PERMISSION_REQUIRED)
                if event.tool in MEMORY_CONFIRM_TOOLS:
                    request_id = event.data.get("request_id", "")
                    request = self._broker.get(request_id) if request_id else None
                    if request:
                        description = describe_proposal(event.tool, request.arguments)
                        self._tasks.publish(
                            record, [ev.memory_proposed(record.task_id, request_id, description)]
                        )
            elif record.status is TaskStatus.PERMISSION_REQUIRED:
                self._tasks.note_status(record, TaskStatus.RUNNING)

        return emit

    def _finalise(self, record: TaskRecord, state: dict[str, Any]) -> TaskRecord:
        task_id = record.task_id
        error = state.get("error")
        if error:
            # The graph already emitted task_error.
            return self._tasks.finish(
                record,
                status=TaskStatus.ERROR,
                response=error.get("message"),
                error=error,
            )

        permission_request = state.get("permission_request")
        if state.get("requires_permission") and permission_request:
            message = permission_request.get("reason") or "Your approval is required."
            self._tasks.publish(record, [ev.task_completed(task_id, message)])
            logger.info("TASK COMPLETE (awaiting permission)", extra={"task_id": task_id})
            return self._tasks.finish(
                record,
                status=TaskStatus.PERMISSION_REQUIRED,
                response=message,
                permission_request=permission_request,
            )

        answer = _final_answer(state.get("messages") or []) or NO_ANSWER
        self._tasks.publish(record, [ev.task_completed(task_id, answer)])
        logger.info("TASK COMPLETE", extra={"task_id": task_id})
        return self._tasks.finish(record, status=TaskStatus.COMPLETED, response=answer)


@lru_cache(maxsize=1)
def get_agent_runner() -> AgentRunner:
    """Runner bound to the process-wide settings, router and task store."""
    return AgentRunner()
