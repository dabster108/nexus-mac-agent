"""Reading what NEXUS remembers.

Read-only on purpose. Forgetting is not exposed here: deletion is a CONFIRM
tool, and the whole point of that classification is that a human approves each
one through the broker. A ``DELETE /api/memory/{id}`` would be a second path
to the same effect with none of the same checks, so the UI's "Forget" action
sends an ordinary chat message instead and gets the ordinary approval prompt.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Query

from app.api.deps import RunnerDep
from app.api.schemas import MemoryListResponse, MemoryResponse

router = APIRouter(prefix="/api/memory", tags=["memory"])


@router.get(
    "",
    response_model=MemoryListResponse,
    summary="List remembered facts",
    description=(
        "Everything NEXUS remembers, with how much it trusts each and when it "
        "was last verified. Read through the same SAFE tool the agent uses, so "
        "this view can never show more than the agent can see."
    ),
)
async def list_memories(
    runner: RunnerDep,
    query: Annotated[
        str | None, Query(description="Filter by keyword.", max_length=200)
    ] = None,
    limit: Annotated[int, Query(ge=1, le=50, description="Maximum results.")] = 50,
) -> MemoryListResponse:
    memories = await runner.list_memories(query, limit)
    return MemoryListResponse(
        memories=[MemoryResponse.model_validate(memory) for memory in memories],
        count=len(memories),
    )
