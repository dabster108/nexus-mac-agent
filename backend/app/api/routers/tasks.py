"""Task inspection and cancellation."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Query

from app.api.deps import RunnerDep, TaskStoreDep
from app.api.schemas import (
    ErrorResponse,
    TaskListResponse,
    TaskResponse,
    TaskStatusResponse,
    TaskSummary,
)

router = APIRouter(prefix="/api/tasks", tags=["tasks"])


@router.get(
    "",
    response_model=TaskListResponse,
    summary="List recent tasks",
    description="Most recent first. Task history is in-memory and bounded.",
)
async def list_tasks(
    tasks: TaskStoreDep,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
) -> TaskListResponse:
    return TaskListResponse(
        tasks=[TaskSummary.from_record(record) for record in tasks.list_tasks(limit)]
    )


@router.get(
    "/{task_id}",
    response_model=TaskResponse,
    summary="Get a task",
    description="The full record, including every execution event emitted so far.",
    responses={404: {"model": ErrorResponse, "description": "Unknown task"}},
)
async def get_task(task_id: str, tasks: TaskStoreDep) -> TaskResponse:
    return TaskResponse.from_record(tasks.require(task_id))


@router.post(
    "/{task_id}/cancel",
    response_model=TaskStatusResponse,
    summary="Cancel a running task",
    description=(
        "Stops a running task and emits a `task_cancelled` event. A task that "
        "has already finished is returned with its real status — cancelling it "
        "is not pretended."
    ),
    responses={404: {"model": ErrorResponse, "description": "Unknown task"}},
)
async def cancel_task(task_id: str, runner: RunnerDep) -> TaskStatusResponse:
    record = await runner.cancel(task_id)
    return TaskStatusResponse(task_id=record.task_id, status=str(record.status))
