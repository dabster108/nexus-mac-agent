"""Suggestions NEXUS is offering.

Read and dismiss. There is deliberately **no** execute endpoint, and this is
the whole security posture of the feature rather than an omission: a route
that acted on a suggestion would be a second path to the machine that skipped
the agent, the tool registry and the approval broker.

Accepting a suggestion is therefore a client-side act — it POSTs the
suggestion's own ``prompt`` to ``/api/chat`` like any other message, and marks
the suggestion accepted here purely so it stops being offered.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, HTTPException, Query, status

from app.api.schemas import (
    ErrorResponse,
    SuggestionListResponse,
    SuggestionResponse,
)
from app.suggestions.store import get_suggestion_store

router = APIRouter(prefix="/api/suggestions", tags=["suggestions"])


@router.get(
    "",
    response_model=SuggestionListResponse,
    summary="List open suggestions",
    description=(
        "Newest first, bounded, expired ones excluded. Live updates arrive on "
        "WS /api/ws as suggestion_created events."
    ),
)
async def list_suggestions(
    limit: Annotated[int, Query(ge=1, le=50)] = 20,
    include_resolved: Annotated[
        bool, Query(description="Include dismissed, accepted and expired.")
    ] = False,
) -> SuggestionListResponse:
    found = get_suggestion_store().list(
        include_resolved=include_resolved, limit=limit
    )
    return SuggestionListResponse(
        suggestions=[
            SuggestionResponse.model_validate(item.to_public_dict()) for item in found
        ],
        count=len(found),
    )


@router.get(
    "/{suggestion_id}",
    response_model=SuggestionResponse,
    summary="Get one suggestion",
    responses={404: {"model": ErrorResponse, "description": "Unknown suggestion"}},
)
async def get_suggestion(suggestion_id: str) -> SuggestionResponse:
    found = get_suggestion_store().get(suggestion_id)
    if found is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Unknown suggestion '{suggestion_id}'.",
        )
    return SuggestionResponse.model_validate(found.to_public_dict())


@router.post(
    "/{suggestion_id}/dismiss",
    response_model=SuggestionResponse,
    summary="Dismiss a suggestion",
    description=(
        "Stops it being offered, and keeps the same condition quiet for a "
        "while so dismissing it means something."
    ),
    responses={404: {"model": ErrorResponse, "description": "Unknown suggestion"}},
)
async def dismiss_suggestion(suggestion_id: str) -> SuggestionResponse:
    store = get_suggestion_store()
    updated = store.dismiss(suggestion_id)
    if updated is None:
        existing = store.get(suggestion_id)
        if existing is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Unknown suggestion '{suggestion_id}'.",
            )
        updated = existing  # already resolved; report its state
    return SuggestionResponse.model_validate(updated.to_public_dict())


@router.post(
    "/{suggestion_id}/accept",
    response_model=SuggestionResponse,
    summary="Record that a suggestion was taken up",
    description=(
        "Marks it accepted so it stops being offered. This executes nothing: "
        "the client sends the suggestion's prompt to /api/chat, and the agent "
        "handles it under the ordinary permission model."
    ),
    responses={404: {"model": ErrorResponse, "description": "Unknown suggestion"}},
)
async def accept_suggestion(suggestion_id: str) -> SuggestionResponse:
    store = get_suggestion_store()
    updated = store.accept(suggestion_id)
    if updated is None:
        existing = store.get(suggestion_id)
        if existing is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Unknown suggestion '{suggestion_id}'.",
            )
        updated = existing
    return SuggestionResponse.model_validate(updated.to_public_dict())
