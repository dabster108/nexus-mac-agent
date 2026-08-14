"""In-memory task tracking and live event fan-out.

Good enough for v1 (BACKEND_SPEC.md §20). Records are bounded so a long-running
process cannot grow without limit. Nothing here is persisted across restarts.
"""

from __future__ import annotations

import asyncio
from collections import OrderedDict
from collections.abc import AsyncIterator, Iterable, Sequence
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from functools import lru_cache
from typing import Any
from uuid import uuid4

from app.agent.events import ExecutionEvent
from app.agent.state import ErrorInfo, PermissionRequest
from app.core.errors import ErrorCode, NexusError

MAX_TASKS = 200
SUBSCRIBER_QUEUE_SIZE = 256


class TaskNotFound(NexusError):
    """No task with that id (it may have aged out of the in-memory store)."""

    code = ErrorCode.VALIDATION_ERROR
    http_status = 404


class TaskStatus(StrEnum):
    RUNNING = "running"
    COMPLETED = "completed"
    PERMISSION_REQUIRED = "permission_required"
    CANCELLED = "cancelled"
    ERROR = "error"

    @property
    def is_terminal(self) -> bool:
        # PERMISSION_REQUIRED is not terminal: the task is paused, not done —
        # `cancel()` must still be able to reach it. (Was `self is not RUNNING`,
        # which silently made every waiting-for-approval task uncancellable.)
        return self in (TaskStatus.COMPLETED, TaskStatus.CANCELLED, TaskStatus.ERROR)


def new_task_id() -> str:
    return f"task_{uuid4().hex}"


def _now() -> str:
    return datetime.now(UTC).isoformat()


@dataclass
class TaskRecord:
    task_id: str
    request: str
    status: TaskStatus = TaskStatus.RUNNING
    response: str | None = None
    events: list[ExecutionEvent] = field(default_factory=list)
    error: ErrorInfo | None = None
    permission_request: PermissionRequest | None = None
    created_at: str = field(default_factory=_now)
    updated_at: str = field(default_factory=_now)
    completed_at: str | None = None

    @property
    def message(self) -> str | None:
        """The latest thing worth showing the user.

        Falls back to the most recent event message while the task is still
        running, so the frontend has something to display before the answer.
        """
        if self.response:
            return self.response
        for event in reversed(self.events):
            if event.message:
                return event.message
        return None

    def to_dict(self) -> dict[str, Any]:
        return {
            "task_id": self.task_id,
            "status": str(self.status),
            "request": self.request,
            "message": self.message,
            "response": self.response,
            "events": [event.to_dict() for event in self.events],
            "error": self.error,
            "permission_request": self.permission_request,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "completed_at": self.completed_at,
        }

    def to_summary(self) -> dict[str, Any]:
        """The lighter shape used by ``GET /api/tasks`` (no event history)."""
        return {
            "task_id": self.task_id,
            "status": str(self.status),
            "request": self.request,
            "message": self.message,
            "created_at": self.created_at,
            "completed_at": self.completed_at,
        }


class TaskStore:
    """Holds task records and broadcasts their events to WebSocket clients."""

    def __init__(self, max_tasks: int = MAX_TASKS) -> None:
        self._tasks: OrderedDict[str, TaskRecord] = OrderedDict()
        self._max_tasks = max_tasks
        self._subscribers: list[asyncio.Queue[dict[str, Any]]] = []
        self._runs: dict[str, asyncio.Task[Any]] = {}

    # --- records -----------------------------------------------------
    def create(self, request: str, task_id: str | None = None) -> TaskRecord:
        record = TaskRecord(task_id=task_id or new_task_id(), request=request)
        self._tasks[record.task_id] = record
        while len(self._tasks) > self._max_tasks:
            self._tasks.popitem(last=False)
        return record

    def get(self, task_id: str) -> TaskRecord | None:
        return self._tasks.get(task_id)

    def require(self, task_id: str) -> TaskRecord:
        record = self._tasks.get(task_id)
        if record is None:
            raise TaskNotFound(f"Unknown task '{task_id}'.")
        return record

    def list_tasks(self, limit: int | None = None) -> list[TaskRecord]:
        """Most recent first."""
        records = list(reversed(self._tasks.values()))
        return records[:limit] if limit else records

    def publish(self, record: TaskRecord, events: Iterable[ExecutionEvent]) -> None:
        """Append events to the record and push them to live subscribers."""
        for event in events:
            record.events.append(event)
            self._broadcast(event.to_dict())
        record.updated_at = _now()

    def finish(
        self,
        record: TaskRecord,
        *,
        status: TaskStatus,
        response: str | None = None,
        error: ErrorInfo | None = None,
        permission_request: PermissionRequest | None = None,
    ) -> TaskRecord:
        record.status = status
        record.response = response
        record.error = error
        record.permission_request = permission_request
        record.updated_at = _now()
        if status.is_terminal:
            record.completed_at = record.updated_at
        return record

    def note_status(self, record: TaskRecord, status: TaskStatus) -> None:
        """Update a non-terminal status mid-run (e.g. waiting on permission)."""
        if record.status.is_terminal or record.status is status:
            return
        record.status = status
        record.updated_at = _now()

    # --- cancellation ------------------------------------------------
    def register_run(self, task_id: str, handle: asyncio.Task[Any]) -> None:
        """Remember the asyncio task executing this run, so it can be cancelled."""
        self._runs[task_id] = handle
        handle.add_done_callback(lambda _: self._runs.pop(task_id, None))

    def is_running(self, task_id: str) -> bool:
        handle = self._runs.get(task_id)
        return handle is not None and not handle.done()

    def request_cancel(self, task_id: str) -> bool:
        """Ask the run to stop. Returns whether a cancellation was issued."""
        handle = self._runs.get(task_id)
        if handle is None or handle.done():
            return False
        handle.cancel()
        return True

    # --- streaming ---------------------------------------------------
    def _broadcast(self, payload: dict[str, Any]) -> None:
        for queue in list(self._subscribers):
            try:
                queue.put_nowait(payload)
            except asyncio.QueueFull:  # pragma: no cover - slow consumer
                self._subscribers.remove(queue)

    @asynccontextmanager
    async def subscribe(self) -> AsyncIterator[asyncio.Queue[dict[str, Any]]]:
        """Yield a queue receiving every event emitted while subscribed."""
        queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue(SUBSCRIBER_QUEUE_SIZE)
        self._subscribers.append(queue)
        try:
            yield queue
        finally:
            if queue in self._subscribers:
                self._subscribers.remove(queue)

    @property
    def subscriber_count(self) -> int:
        return len(self._subscribers)


def replay(record: TaskRecord) -> Sequence[dict[str, Any]]:
    """Serialise a record's events (used when a client connects late)."""
    return [event.to_dict() for event in record.events]


@lru_cache(maxsize=1)
def get_task_store() -> TaskStore:
    return TaskStore()
