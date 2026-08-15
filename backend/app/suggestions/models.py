"""What a suggestion is, and — more importantly — what it is not.

A suggestion is a *sentence offered to a person*. It carries no authority and
performs nothing. The ``suggested_action`` field is the one place where that
distinction could quietly erode, so it is deliberately inert: an intent name
and a few identifiers, with no tool name, no arguments, and nothing the
execution path reads. Accepting a suggestion produces an ordinary chat
message; from there the agent picks its own tools and CONFIRM still means
CONFIRM.

Text is sanitised on the way in for the same reason it is in
:mod:`app.observations.models` — a suggestion quotes an observation, which
quoted a branch name or a line of process output.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from typing import Any
from uuid import uuid4

from app.observations.models import Severity, clean

#: Bounded like everything else. A person will not read past a handful, and a
#: pile of stale suggestions is worse than none.
MAX_SUGGESTIONS = 50
MAX_PENDING = 12
MAX_TITLE_CHARS = 120
MAX_DESCRIPTION_CHARS = 300
MAX_REASON_CHARS = 200

#: How long a suggestion stays useful. A crash worth investigating an hour
#: later is not worth investigating tomorrow.
DEFAULT_TTL_SECONDS = 3600.0


class Category(StrEnum):
    PROCESS = "PROCESS"
    SERVICE = "SERVICE"
    WORKSPACE = "WORKSPACE"
    MEMORY = "MEMORY"
    TASK = "TASK"


class Status(StrEnum):
    PENDING = "PENDING"
    ACCEPTED = "ACCEPTED"
    DISMISSED = "DISMISSED"
    EXPIRED = "EXPIRED"


def new_suggestion_id() -> str:
    return f"sug_{uuid4().hex[:12]}"


def _now() -> datetime:
    return datetime.now(UTC)


@dataclass(frozen=True, slots=True)
class SuggestedAction:
    """What accepting this would *ask about*. Never what would be run.

    Holds an intent label and identifiers only. There is deliberately no tool
    name and no arguments here: if this carried them, something downstream
    would eventually be tempted to use them, and that would be a second
    execution path around the agent and the broker.
    """

    intent: str
    process_id: str | None = None
    memory_key: str | None = None
    workspace: str | None = None
    #: The sentence sent to /api/chat when the user accepts. Composed here so
    #: there is one place that decides what accepting actually asks for.
    prompt: str = ""

    def to_public_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {"intent": self.intent, "prompt": self.prompt}
        for name in ("process_id", "memory_key", "workspace"):
            value = getattr(self, name)
            if value:
                payload[name] = value
        return payload


@dataclass(frozen=True, slots=True)
class Suggestion:
    """Something NEXUS thinks might be worth doing. The user decides."""

    category: Category
    severity: Severity
    title: str
    description: str
    reason: str
    action: SuggestedAction
    #: Collapses the several ways one condition could be phrased into a single
    #: logical suggestion — "backend crashed" and "process failed" are one.
    key: str
    suggestion_id: str = field(default_factory=new_suggestion_id)
    observation_id: str | None = None
    status: Status = Status.PENDING
    created_at: str = field(default_factory=lambda: _now().isoformat())
    expires_at: str = field(
        default_factory=lambda: (_now() + timedelta(seconds=DEFAULT_TTL_SECONDS)).isoformat()
    )

    @classmethod
    def build(
        cls,
        *,
        category: Category,
        severity: Severity,
        title: str,
        description: str,
        reason: str,
        action: SuggestedAction,
        key: str,
        observation_id: str | None = None,
        ttl_seconds: float = DEFAULT_TTL_SECONDS,
    ) -> Suggestion:
        """The only supported constructor, so nothing skips sanitising."""
        return cls(
            category=category,
            severity=severity,
            title=clean(title, MAX_TITLE_CHARS),
            description=clean(description, MAX_DESCRIPTION_CHARS),
            reason=clean(reason, MAX_REASON_CHARS),
            action=SuggestedAction(
                intent=clean(action.intent, 40),
                process_id=clean(action.process_id, 60) or None,
                memory_key=clean(action.memory_key, 80) or None,
                workspace=clean(action.workspace, 200) or None,
                prompt=clean(action.prompt, 400),
            ),
            key=clean(key, 120),
            observation_id=clean(observation_id, 60) or None,
            expires_at=(_now() + timedelta(seconds=ttl_seconds)).isoformat(),
        )

    @property
    def is_pending(self) -> bool:
        return self.status is Status.PENDING

    def has_expired(self, now: datetime | None = None) -> bool:
        try:
            deadline = datetime.fromisoformat(self.expires_at)
        except (TypeError, ValueError):  # pragma: no cover - defensive
            return False
        return (now or _now()) >= deadline

    def with_status(self, status: Status) -> Suggestion:
        return Suggestion(
            category=self.category,
            severity=self.severity,
            title=self.title,
            description=self.description,
            reason=self.reason,
            action=self.action,
            key=self.key,
            suggestion_id=self.suggestion_id,
            observation_id=self.observation_id,
            status=status,
            created_at=self.created_at,
            expires_at=self.expires_at,
        )

    def to_public_dict(self) -> dict[str, Any]:
        return {
            "suggestion_id": self.suggestion_id,
            "category": str(self.category),
            "severity": str(self.severity),
            "title": self.title,
            "description": self.description,
            "reason": self.reason,
            "suggested_action": self.action.to_public_dict(),
            "observation_id": self.observation_id,
            "status": str(self.status),
            "created_at": self.created_at,
            "expires_at": self.expires_at,
        }


__all__ = [
    "DEFAULT_TTL_SECONDS",
    "MAX_PENDING",
    "MAX_SUGGESTIONS",
    "Category",
    "Status",
    "SuggestedAction",
    "Suggestion",
]
