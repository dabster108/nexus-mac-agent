"""Permission requests.

A ``CONFIRM`` tool call parks here while the agent waits. Approving or denying
resolves the request and wakes the run up.
"""

from __future__ import annotations

from fastapi import APIRouter

from app.api.deps import BrokerDep
from app.api.schemas import (
    ErrorResponse,
    PermissionListResponse,
    PermissionRequestResponse,
    PermissionResponse,
)

router = APIRouter(prefix="/api/permissions", tags=["permissions"])

_DECISION_RESPONSES = {
    404: {"model": ErrorResponse, "description": "Unknown permission request"},
    409: {"model": ErrorResponse, "description": "Already approved, denied or expired"},
}


@router.get(
    "/pending",
    response_model=PermissionListResponse,
    summary="List pending permission requests",
    description="Tool calls currently waiting on the user, oldest first.",
)
async def list_pending(broker: BrokerDep) -> PermissionListResponse:
    return PermissionListResponse(
        requests=[
            PermissionRequestResponse.from_request(request)
            for request in broker.list_pending()
        ]
    )


@router.post(
    "/{request_id}/approve",
    response_model=PermissionResponse,
    summary="Approve a permission request",
    description="Releases the waiting task so the tool can run.",
    responses=_DECISION_RESPONSES,
)
async def approve(request_id: str, broker: BrokerDep) -> PermissionResponse:
    request = broker.approve(request_id)
    return PermissionResponse(request_id=request.request_id, status=str(request.status))


@router.post(
    "/{request_id}/deny",
    response_model=PermissionResponse,
    summary="Deny a permission request",
    description=(
        "Releases the waiting task with a refusal. The agent is told the user "
        "declined and continues from there."
    ),
    responses=_DECISION_RESPONSES,
)
async def deny(request_id: str, broker: BrokerDep) -> PermissionResponse:
    request = broker.deny(request_id)
    return PermissionResponse(request_id=request.request_id, status=str(request.status))
