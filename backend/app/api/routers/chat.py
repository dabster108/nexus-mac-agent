"""Chat entry point."""

from __future__ import annotations

from fastapi import APIRouter, status

from app.api.deps import RunnerDep
from app.api.schemas import ChatRequest, ChatResponse, ErrorResponse

router = APIRouter(prefix="/api", tags=["agent"])


@router.post(
    "/chat",
    response_model=ChatResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Send a message to the agent",
    description=(
        "Creates a task and runs it in the background. Subscribe to `WS /api/ws` "
        "(optionally with `?task_id=`) for live events, or poll "
        "`GET /api/tasks/{task_id}` for the result."
    ),
    responses={400: {"model": ErrorResponse, "description": "Invalid request"}},
)
async def chat(request: ChatRequest, runner: RunnerDep) -> ChatResponse:
    record = runner.start(
        request.message,
        provider=request.provider,
        approved_tools=request.approved_tools,
    )
    return ChatResponse(task_id=record.task_id, status="started")
