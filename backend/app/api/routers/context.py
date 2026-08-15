"""What NEXUS can currently see: workspace, processes, memory, machine.

Read-only, and deliberately thin — §23's rule. The panel gets exactly the
context object the agent would be given, rendered through the same
``to_public_dict``, so the sidebar cannot drift from what actually informed an
answer. No agent logic lives here.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, status

from app.api.deps import RunnerDep
from app.api.schemas import ContextResponse, ErrorResponse

router = APIRouter(prefix="/api/context", tags=["context"])


@router.get(
    "",
    response_model=ContextResponse,
    summary="Current workspace, processes and relevant memory",
    description=(
        "A snapshot gathered through SAFE tools only. Briefly cached, so "
        "polling this endpoint does not re-scan the workspace on every call."
    ),
)
async def current_context(runner: RunnerDep) -> ContextResponse:
    context = await runner.current_context()
    return ContextResponse.model_validate(context.to_public_dict())


@router.get(
    "/{task_id}",
    response_model=ContextResponse,
    summary="The context that informed one task",
    description=(
        "What the agent was actually given before answering — the transparency "
        "view behind 'used memory'."
    ),
    responses={404: {"model": ErrorResponse, "description": "Unknown task"}},
)
async def context_for_task(task_id: str, runner: RunnerDep) -> ContextResponse:
    context = runner.context_for(task_id)
    if context is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No context was recorded for task '{task_id}'.",
        )
    return ContextResponse.model_validate(context.to_public_dict())
