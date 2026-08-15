"""Structured execution events.

These are the only agent internals the frontend ever sees. They carry status
and concise, user-facing messages — never hidden chain-of-thought, never tool
argument values.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any


class EventType(StrEnum):
    TASK_STARTED = "task_started"
    AGENT_MESSAGE = "agent_message"
    TOOL_REQUESTED = "tool_requested"
    PERMISSION_REQUIRED = "permission_required"
    TOOL_STARTED = "tool_started"
    TOOL_COMPLETED = "tool_completed"
    TASK_COMPLETED = "task_completed"
    TASK_CANCELLED = "task_cancelled"
    TASK_ERROR = "task_error"

    # --- mission: a multi-step objective, orchestrated over several of the
    # events above. No second streaming system — these ride the same
    # ExecutionEvent/EventSink/WebSocket path as everything else.
    MISSION_STARTED = "mission_started"
    MISSION_PLAN_CREATED = "mission_plan_created"
    MISSION_STEP_STARTED = "mission_step_started"
    MISSION_STEP_COMPLETED = "mission_step_completed"
    MISSION_STEP_FAILED = "mission_step_failed"
    MISSION_STEP_SKIPPED = "mission_step_skipped"
    MISSION_WAITING_APPROVAL = "mission_waiting_approval"
    MISSION_COMPLETED = "mission_completed"
    MISSION_FAILED = "mission_failed"
    MISSION_CANCELLED = "mission_cancelled"

    # --- memory & context: gathered before planning, or changed by a tool
    # call. Same ExecutionEvent/EventSink/WebSocket path as everything else.
    MEMORY_RETRIEVED = "memory_retrieved"
    MEMORY_PROPOSED = "memory_proposed"
    MEMORY_SAVED = "memory_saved"
    MEMORY_DELETED = "memory_deleted"
    MEMORY_CONFLICT = "memory_conflict"
    WORKSPACE_DETECTED = "workspace_detected"
    CONTEXT_COLLECTED = "context_collected"

    # --- observations: things NEXUS noticed on its own rather than because it
    # was asked. Same stream as everything else — an observation is not tied to
    # a task, so it carries the synthetic task id below.
    OBSERVATION_CREATED = "observation_created"
    OBSERVATION_DISMISSED = "observation_dismissed"

    # --- suggestions: a next step offered to the user. Never an action — the
    # user accepting one produces an ordinary chat message.
    SUGGESTION_CREATED = "suggestion_created"
    SUGGESTION_DISMISSED = "suggestion_dismissed"
    SUGGESTION_EXPIRED = "suggestion_expired"


def _now() -> str:
    return datetime.now(UTC).isoformat()


@dataclass(frozen=True, slots=True)
class ExecutionEvent:
    type: EventType
    task_id: str
    timestamp: str = field(default_factory=_now)
    message: str | None = None
    tool: str | None = None
    data: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "type": str(self.type),
            "task_id": self.task_id,
            "timestamp": self.timestamp,
        }
        if self.message is not None:
            payload["message"] = self.message
        if self.tool is not None:
            payload["tool"] = self.tool
        if self.data:
            payload.update(self.data)
        return payload


EventSink = Callable[[ExecutionEvent], None]
"""Delivers an event the moment it happens.

LangGraph only surfaces a node's state update once the node *returns*. A node
that blocks — waiting for the user to approve a tool — must still get its
events out, or the frontend would never see the request it is being asked to
answer. Nodes therefore call the sink as they go and also return the events in
state.
"""


def no_sink(event: ExecutionEvent) -> None:
    """Default sink: drop the event (state still carries it)."""


def task_started(task_id: str, request: str) -> ExecutionEvent:
    return ExecutionEvent(
        type=EventType.TASK_STARTED, task_id=task_id, message=request
    )


def agent_message(task_id: str, message: str) -> ExecutionEvent:
    return ExecutionEvent(
        type=EventType.AGENT_MESSAGE, task_id=task_id, message=message
    )


def tool_requested(task_id: str, tool: str, permission: str) -> ExecutionEvent:
    return ExecutionEvent(
        type=EventType.TOOL_REQUESTED,
        task_id=task_id,
        tool=tool,
        message=f"Requested tool '{tool}'.",
        data={"permission": permission},
    )


def permission_required(
    task_id: str,
    tool: str,
    permission: str,
    reason: str,
    request_id: str | None = None,
) -> ExecutionEvent:
    data: dict[str, Any] = {"permission": permission}
    if request_id:
        # The frontend answers with POST /api/permissions/{request_id}/approve.
        data["request_id"] = request_id
    return ExecutionEvent(
        type=EventType.PERMISSION_REQUIRED,
        task_id=task_id,
        tool=tool,
        message=reason,
        data=data,
    )


def tool_started(task_id: str, tool: str) -> ExecutionEvent:
    return ExecutionEvent(
        type=EventType.TOOL_STARTED,
        task_id=task_id,
        tool=tool,
        message=f"Running '{tool}'.",
    )


def tool_completed(task_id: str, tool: str, success: bool, message: str | None = None) -> ExecutionEvent:
    return ExecutionEvent(
        type=EventType.TOOL_COMPLETED,
        task_id=task_id,
        tool=tool,
        message=message or (f"'{tool}' finished." if success else f"'{tool}' failed."),
        data={"success": success},
    )


def task_completed(task_id: str, message: str | None = None) -> ExecutionEvent:
    return ExecutionEvent(
        type=EventType.TASK_COMPLETED, task_id=task_id, message=message
    )


def task_cancelled(task_id: str, message: str = "The task was cancelled.") -> ExecutionEvent:
    return ExecutionEvent(
        type=EventType.TASK_CANCELLED, task_id=task_id, message=message
    )


def task_error(task_id: str, code: str, message: str) -> ExecutionEvent:
    return ExecutionEvent(
        type=EventType.TASK_ERROR,
        task_id=task_id,
        message=message,
        data={"code": code},
    )


# --- mission events ----------------------------------------------------
#
# Every mission event carries ``mission_id`` and, once a plan exists,
# ``step_id`` — always in ``data``, the same place ``permission_required``
# already puts ``request_id``. A future mission UI can key off these without
# any change to the event envelope.


def mission_started(task_id: str, mission_id: str, objective: str) -> ExecutionEvent:
    return ExecutionEvent(
        type=EventType.MISSION_STARTED,
        task_id=task_id,
        message=objective,
        data={"mission_id": mission_id},
    )


def mission_plan_created(
    task_id: str, mission_id: str, steps: list[dict[str, Any]]
) -> ExecutionEvent:
    return ExecutionEvent(
        type=EventType.MISSION_PLAN_CREATED,
        task_id=task_id,
        message=f"Planned {len(steps)} step(s).",
        data={"mission_id": mission_id, "steps": steps},
    )


def mission_step_started(
    task_id: str, mission_id: str, step_id: str, description: str
) -> ExecutionEvent:
    return ExecutionEvent(
        type=EventType.MISSION_STEP_STARTED,
        task_id=task_id,
        message=description,
        data={"mission_id": mission_id, "step_id": step_id},
    )


def mission_step_completed(
    task_id: str, mission_id: str, step_id: str, message: str | None = None
) -> ExecutionEvent:
    return ExecutionEvent(
        type=EventType.MISSION_STEP_COMPLETED,
        task_id=task_id,
        message=message,
        data={"mission_id": mission_id, "step_id": step_id},
    )


def mission_step_failed(
    task_id: str, mission_id: str, step_id: str, reason: str
) -> ExecutionEvent:
    return ExecutionEvent(
        type=EventType.MISSION_STEP_FAILED,
        task_id=task_id,
        message=reason,
        data={"mission_id": mission_id, "step_id": step_id},
    )


def mission_step_skipped(
    task_id: str, mission_id: str, step_id: str, reason: str
) -> ExecutionEvent:
    return ExecutionEvent(
        type=EventType.MISSION_STEP_SKIPPED,
        task_id=task_id,
        message=reason,
        data={"mission_id": mission_id, "step_id": step_id},
    )


def mission_waiting_approval(
    task_id: str, mission_id: str, step_id: str, request_id: str, reason: str
) -> ExecutionEvent:
    return ExecutionEvent(
        type=EventType.MISSION_WAITING_APPROVAL,
        task_id=task_id,
        message=reason,
        data={"mission_id": mission_id, "step_id": step_id, "request_id": request_id},
    )


def mission_completed(
    task_id: str, mission_id: str, summary: dict[str, Any]
) -> ExecutionEvent:
    return ExecutionEvent(
        type=EventType.MISSION_COMPLETED,
        task_id=task_id,
        message="Mission completed.",
        data={"mission_id": mission_id, "summary": summary},
    )


def mission_failed(
    task_id: str, mission_id: str, reason: str, summary: dict[str, Any]
) -> ExecutionEvent:
    return ExecutionEvent(
        type=EventType.MISSION_FAILED,
        task_id=task_id,
        message=reason,
        data={"mission_id": mission_id, "summary": summary},
    )


def mission_cancelled(
    task_id: str, mission_id: str, message: str = "The mission was cancelled."
) -> ExecutionEvent:
    return ExecutionEvent(
        type=EventType.MISSION_CANCELLED,
        task_id=task_id,
        message=message,
        data={"mission_id": mission_id},
    )


# --- memory & context events --------------------------------------------


def memory_retrieved(task_id: str, count: int, query: str) -> ExecutionEvent:
    return ExecutionEvent(
        type=EventType.MEMORY_RETRIEVED,
        task_id=task_id,
        message=f"Found {count} relevant memor{'y' if count == 1 else 'ies'}.",
        data={"count": count, "query": query},
    )


def memory_proposed(task_id: str, request_id: str, description: str) -> ExecutionEvent:
    return ExecutionEvent(
        type=EventType.MEMORY_PROPOSED,
        task_id=task_id,
        message=description,
        data={"request_id": request_id},
    )


def memory_saved(task_id: str, memory_id: str, key: str) -> ExecutionEvent:
    return ExecutionEvent(
        type=EventType.MEMORY_SAVED,
        task_id=task_id,
        message=f"Remembered '{key}'.",
        data={"memory_id": memory_id, "key": key},
    )


def memory_deleted(task_id: str, count: int, description: str) -> ExecutionEvent:
    return ExecutionEvent(
        type=EventType.MEMORY_DELETED,
        task_id=task_id,
        message=description,
        data={"count": count},
    )


def memory_conflict(task_id: str, key: str, reason: str) -> ExecutionEvent:
    return ExecutionEvent(
        type=EventType.MEMORY_CONFLICT,
        task_id=task_id,
        message=reason,
        data={"key": key},
    )


def workspace_detected(task_id: str, path: str, verified: bool) -> ExecutionEvent:
    return ExecutionEvent(
        type=EventType.WORKSPACE_DETECTED,
        task_id=task_id,
        message=f"{'Verified' if verified else 'Could not verify'} workspace at {path}.",
        data={"path": path, "verified": verified},
    )


def context_collected(task_id: str, summary: dict[str, Any]) -> ExecutionEvent:
    return ExecutionEvent(
        type=EventType.CONTEXT_COLLECTED,
        task_id=task_id,
        message="Context gathered for planning.",
        data={"summary": summary},
    )
