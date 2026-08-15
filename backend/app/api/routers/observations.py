"""What NEXUS noticed on its own.

Read-only plus dismissal. There is deliberately no "act on this" endpoint:
acting is what the agent does, through the tool registry and the approval
broker, and giving observations their own action route would be a second path
to the machine with none of those checks. The frontend's "Investigate" button
sends an ordinary chat message instead.

Observations are also streamed over the existing WebSocket, so these endpoints
exist for the initial load and for a client that reconnects — not for polling.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, HTTPException, Query, status

from app.api.schemas import (
    ErrorResponse,
    ObservationListResponse,
    ObservationResponse,
)
from app.observations.store import get_observation_store

router = APIRouter(prefix="/api/observations", tags=["observations"])


@router.get(
    "",
    response_model=ObservationListResponse,
    summary="List recent observations",
    description=(
        "Newest first, bounded. Dismissed observations are hidden unless asked "
        "for. Live updates arrive on WS /api/ws as observation_created events."
    ),
)
async def list_observations(
    limit: Annotated[int, Query(ge=1, le=200, description="Maximum results.")] = 50,
    include_dismissed: Annotated[
        bool, Query(description="Include ones already dismissed.")
    ] = False,
) -> ObservationListResponse:
    found = get_observation_store().list(
        limit=limit, include_dismissed=include_dismissed
    )
    return ObservationListResponse(
        observations=[
            ObservationResponse.model_validate(item.to_public_dict()) for item in found
        ],
        count=len(found),
    )


@router.get(
    "/{observation_id}",
    response_model=ObservationResponse,
    summary="Get one observation",
    responses={404: {"model": ErrorResponse, "description": "Unknown observation"}},
)
async def get_observation(observation_id: str) -> ObservationResponse:
    found = get_observation_store().get(observation_id)
    if found is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Unknown observation '{observation_id}'.",
        )
    return ObservationResponse.model_validate(found.to_public_dict())


@router.post(
    "/{observation_id}/dismiss",
    response_model=ObservationResponse,
    summary="Dismiss an observation",
    description=(
        "Marks it handled. The record is kept rather than deleted, so the "
        "activity history stays honest."
    ),
    responses={404: {"model": ErrorResponse, "description": "Unknown observation"}},
)
async def dismiss_observation(observation_id: str) -> ObservationResponse:
    store = get_observation_store()
    updated = store.dismiss(observation_id)
    if updated is None:
        existing = store.get(observation_id)
        if existing is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Unknown observation '{observation_id}'.",
            )
        updated = existing  # already dismissed; report its state rather than erroring
    return ObservationResponse.model_validate(updated.to_public_dict())
