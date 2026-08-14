"""Pending approval requests.

When the agent wants to run a ``CONFIRM`` tool it registers a request here and
waits. The API layer surfaces pending requests, and approve/deny wakes the
waiting run up. This is the *runtime* side of permissions; the classification
of a tool into SAFE/CONFIRM/RESTRICTED lives in :mod:`app.tools.permissions`.

Nothing is persisted: a restart drops pending requests, which is the safe
direction to fail in.
"""

from __future__ import annotations

import asyncio
from collections import OrderedDict
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from functools import lru_cache
from typing import Any
from uuid import uuid4

from app.core.errors import ErrorCode, NexusError
from app.core.logging import get_logger
from app.tools.permissions import PermissionLevel

logger = get_logger(__name__)

MAX_REQUESTS = 200


class ApprovalStatus(StrEnum):
    PENDING = "pending"
    APPROVED = "approved"
    DENIED = "denied"
    EXPIRED = "expired"
    CANCELLED = "cancelled"


class ApprovalNotFound(NexusError):
    """No such approval request."""

    code = ErrorCode.VALIDATION_ERROR
    http_status = 404


class ApprovalAlreadyResolved(NexusError):
    """The request has already been approved, denied, expired or cancelled."""

    code = ErrorCode.PERMISSION_ERROR
    http_status = 409


def new_request_id() -> str:
    return f"perm_{uuid4().hex[:16]}"


def _now() -> str:
    return datetime.now(UTC).isoformat()


@dataclass
class ApprovalRequest:
    """One tool call waiting on the user."""

    request_id: str
    task_id: str
    tool: str
    permission: PermissionLevel
    description: str
    arguments: dict[str, Any] = field(default_factory=dict)
    status: ApprovalStatus = ApprovalStatus.PENDING
    created_at: str = field(default_factory=_now)
    resolved_at: str | None = None
    _event: asyncio.Event = field(default_factory=asyncio.Event, repr=False)

    @property
    def is_pending(self) -> bool:
        return self.status is ApprovalStatus.PENDING

    def to_dict(self) -> dict[str, Any]:
        # `arguments` is included deliberately: approving a tool call blind
        # would defeat the point of asking.
        return {
            "request_id": self.request_id,
            "task_id": self.task_id,
            "tool": self.tool,
            "permission": str(self.permission),
            "description": self.description,
            "arguments": self.arguments,
            "status": str(self.status),
            "created_at": self.created_at,
            "resolved_at": self.resolved_at,
        }


class ApprovalBroker:
    """Creates approval requests and resolves them."""

    def __init__(self, max_requests: int = MAX_REQUESTS) -> None:
        self._requests: OrderedDict[str, ApprovalRequest] = OrderedDict()
        self._max_requests = max_requests

    # --- agent side --------------------------------------------------
    def create(
        self,
        *,
        task_id: str,
        tool: str,
        permission: PermissionLevel,
        description: str,
        arguments: Mapping[str, Any] | None = None,
    ) -> ApprovalRequest:
        request = ApprovalRequest(
            request_id=new_request_id(),
            task_id=task_id,
            tool=tool,
            permission=permission,
            description=description,
            arguments=dict(arguments or {}),
        )
        self._requests[request.request_id] = request
        while len(self._requests) > self._max_requests:
            _, dropped = self._requests.popitem(last=False)
            if dropped.is_pending:  # pragma: no cover - only under heavy load
                dropped.status = ApprovalStatus.EXPIRED
                dropped._event.set()
        logger.info(
            "Approval %s requested for '%s'", request.request_id, tool,
            extra={"task_id": task_id},
        )
        return request

    async def wait(self, request: ApprovalRequest, timeout: float) -> ApprovalStatus:
        """Block until the user decides, or the request expires.

        The request is dropped from the pending set on the way out however this
        returns, including cancellation.
        """
        try:
            async with asyncio.timeout(timeout):
                await request._event.wait()
        except TimeoutError:
            if request.is_pending:
                self._resolve(request, ApprovalStatus.EXPIRED)
        except asyncio.CancelledError:
            if request.is_pending:
                self._resolve(request, ApprovalStatus.CANCELLED)
            raise
        return request.status

    def previous_refusal(self, task_id: str, tool: str) -> ApprovalStatus | None:
        """The outcome of an earlier request for this tool, if it was refused.

        A decision sticks for the rest of the task. Without this, a model that
        retries a denied tool would put the same prompt in front of the user on
        every iteration — and someone clicking through repeated dialogs is
        exactly how an unwanted action gets approved.
        """
        for request in reversed(self._requests.values()):
            if request.task_id != task_id or request.tool != tool:
                continue
            if request.status in (
                ApprovalStatus.DENIED,
                ApprovalStatus.EXPIRED,
                ApprovalStatus.CANCELLED,
            ):
                return request.status
        return None

    def cancel_for_task(self, task_id: str) -> list[ApprovalRequest]:
        """Resolve everything still pending for a task (used when it stops)."""
        cancelled = [
            request
            for request in self._requests.values()
            if request.task_id == task_id and request.is_pending
        ]
        for request in cancelled:
            self._resolve(request, ApprovalStatus.CANCELLED)
        return cancelled

    # --- api side ----------------------------------------------------
    def list_pending(self) -> list[ApprovalRequest]:
        return [request for request in self._requests.values() if request.is_pending]

    def get(self, request_id: str) -> ApprovalRequest | None:
        return self._requests.get(request_id)

    def require(self, request_id: str) -> ApprovalRequest:
        request = self._requests.get(request_id)
        if request is None:
            raise ApprovalNotFound(f"Unknown permission request '{request_id}'.")
        return request

    def approve(self, request_id: str) -> ApprovalRequest:
        return self._decide(request_id, ApprovalStatus.APPROVED)

    def deny(self, request_id: str) -> ApprovalRequest:
        return self._decide(request_id, ApprovalStatus.DENIED)

    def _decide(self, request_id: str, status: ApprovalStatus) -> ApprovalRequest:
        request = self.require(request_id)
        if not request.is_pending:
            raise ApprovalAlreadyResolved(
                f"Permission request '{request_id}' is already {request.status}."
            )
        self._resolve(request, status)
        logger.info(
            "Approval %s %s for '%s'", request_id, status, request.tool,
            extra={"task_id": request.task_id},
        )
        return request

    def _resolve(self, request: ApprovalRequest, status: ApprovalStatus) -> None:
        request.status = status
        request.resolved_at = _now()
        request._event.set()


class _Blanks(dict):
    """Renders an unknown placeholder as itself rather than raising."""

    def __missing__(self, key: str) -> str:  # pragma: no cover - defensive
        return f"{{{key}}}"


def describe(
    tool: str,
    description: str,
    arguments: Mapping[str, Any],
    template: str | None = None,
) -> str:
    """A short, human-readable summary of what is being asked for.

    This is what the approval prompt shows, so it stays to one sentence plus
    the arguments in plain form — a tool's full description is written for the
    model, not for someone deciding whether to allow something.

    A tool may supply its own ``template`` (through MCP metadata) when the
    generic phrasing would read poorly; "Run pytest in ~/Projects/nexus" beats
    anything assembled from a description and a key-value list.
    """
    if template:
        try:
            return template.format_map(_Blanks(arguments)).strip()
        except (ValueError, IndexError):  # pragma: no cover - malformed template
            pass

    summary = (description or "").strip().split(". ")[0].rstrip(".").strip()
    summary = summary or f"Run {tool}"
    if not arguments:
        return summary
    rendered = ", ".join(f"{key}: {value}" for key, value in sorted(arguments.items()))
    return f"{summary} ({rendered})"


@lru_cache(maxsize=1)
def get_approval_broker() -> ApprovalBroker:
    return ApprovalBroker()


__all__ = [
    "ApprovalAlreadyResolved",
    "ApprovalBroker",
    "ApprovalNotFound",
    "ApprovalRequest",
    "ApprovalStatus",
    "describe",
    "get_approval_broker",
]
