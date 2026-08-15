"""The vocabulary of the memory system.

Deliberately not ``memory = []``: every fact NEXUS remembers has a declared
type, a source, and a lifecycle state, so the store can be reasoned about and
queried structurally instead of scanned like a diary.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any
from uuid import uuid4


class MemoryType(StrEnum):
    USER_PREFERENCE = "USER_PREFERENCE"
    """How the user likes things done — not a fact about the world."""

    PROJECT = "PROJECT"
    """A named project: its location, what it is."""

    WORKSPACE = "WORKSPACE"
    """A part of a project — a service, a directory — and how to work with it."""

    WORKFLOW = "WORKFLOW"
    """A recurring sequence: how this user builds, tests, deploys."""

    DECISION = "DECISION"
    """A choice made about a project and the reason for it — "we moved the API
    to port 8123". Durable in a way status ("the build is broken") is not."""

    TASK_CONTEXT = "TASK_CONTEXT"
    """What the user was last working on, so a later session can pick it up.
    The one memory type that is *about* a moment rather than a stable fact,
    which is why it carries its own recency in the value."""

    FACT = "FACT"
    """Anything stable that doesn't fit the above."""


class MemorySource(StrEnum):
    USER = "USER"
    """The user said so, directly."""

    SYSTEM = "SYSTEM"
    """NEXUS derived it from inspecting the machine."""

    MISSION = "MISSION"
    """Discovered while carrying out a mission."""


class MemoryStatus(StrEnum):
    PROPOSED = "PROPOSED"
    """Not yet written. Exists only as an approval request in flight."""

    ACTIVE = "ACTIVE"
    STALE = "STALE"
    """Computed at read time (e.g. a remembered path no longer exists) —
    never itself the stored value, so a memory can't go stale in the
    database and then silently stay that way once the world changes back."""

    DELETED = "DELETED"
    """Soft-deleted: the row remains for audit, but is never returned by an
    ordinary list/get/search."""


#: Confidence assigned by default, keyed by source. The user saying something
#: is trusted outright; something inferred during a mission less so.
DEFAULT_CONFIDENCE: dict[MemorySource, float] = {
    MemorySource.USER: 1.0,
    MemorySource.SYSTEM: 0.85,
    MemorySource.MISSION: 0.6,
}


class ConfidenceLevel(StrEnum):
    """How much weight a memory should carry, as a word rather than a float.

    A model reasons about "HIGH" far more reliably than about 0.85, and the
    precedence rule is stated in these terms. The float stays the stored
    value; this is the reading of it.
    """

    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"


#: After this long without re-verification, a memory that was once trusted is
#: reported one level lower. It is not wrong — nobody has checked it lately.
VERIFICATION_HALF_LIFE_DAYS = 14

# Placed so the four cases §3 names land where it says they should:
#   USER 1.0    (explicit statement)  -> HIGH
#   SYSTEM 0.85 (verified tool result) -> HIGH
#   MISSION 0.6 (agent inference)      -> LOW
#   a decayed HIGH (0.79)              -> MEDIUM
_HIGH_THRESHOLD = 0.8
_MEDIUM_THRESHOLD = 0.7


def confidence_level(
    confidence: float, *, age_days: float | None = None
) -> ConfidenceLevel:
    """Read a stored confidence as HIGH/MEDIUM/LOW, decayed by staleness.

    An explicit user statement and a verified tool result both start HIGH; an
    inference during a mission starts LOW. A HIGH memory nobody has verified
    in a fortnight is reported MEDIUM — old-but-unverified is exactly the
    case where live evidence should win without a fight.
    """
    if age_days is not None and age_days > VERIFICATION_HALF_LIFE_DAYS:
        confidence = min(confidence, _HIGH_THRESHOLD - 0.01)
    if confidence >= _HIGH_THRESHOLD:
        return ConfidenceLevel.HIGH
    if confidence >= _MEDIUM_THRESHOLD:
        return ConfidenceLevel.MEDIUM
    return ConfidenceLevel.LOW


def new_memory_id() -> str:
    return f"mem_{uuid4().hex[:12]}"


def _now() -> str:
    return datetime.now(UTC).isoformat()


@dataclass(frozen=True, slots=True)
class Memory:
    """One remembered fact."""

    id: str
    type: MemoryType
    key: str
    value: dict[str, Any]
    source: MemorySource
    confidence: float
    status: MemoryStatus = MemoryStatus.ACTIVE
    created_at: str = field(default_factory=_now)
    updated_at: str = field(default_factory=_now)
    #: When live evidence last agreed with this memory. Distinct from
    #: ``updated_at``, which only says when the value was last written:
    #: a memory can be years old and still verified minutes ago.
    last_verified_at: str | None = None

    @property
    def age_days(self) -> float | None:
        """Days since this memory was last verified against the world."""
        reference = self.last_verified_at or self.updated_at
        try:
            then = datetime.fromisoformat(reference)
        except (TypeError, ValueError):  # pragma: no cover - defensive
            return None
        if then.tzinfo is None:  # pragma: no cover - legacy rows
            then = then.replace(tzinfo=UTC)
        return (datetime.now(UTC) - then).total_seconds() / 86_400

    @property
    def confidence_level(self) -> ConfidenceLevel:
        return confidence_level(self.confidence, age_days=self.age_days)

    def to_public_dict(self, *, stale: bool = False, conflict: str | None = None) -> dict[str, Any]:
        """The shape returned by the MCP tools.

        ``stale``/``conflict`` are supplied by the caller (the store computes
        path staleness at read time; conflicts are detected by the context
        collector against live evidence) — neither is a column on this row.
        """
        payload: dict[str, Any] = {
            "id": self.id,
            "type": str(self.type),
            "key": self.key,
            "value": self.value,
            "source": str(self.source),
            "confidence": self.confidence,
            "confidence_level": str(self.confidence_level),
            "status": str(self.status),
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "last_verified_at": self.last_verified_at,
        }
        if stale or self.status is MemoryStatus.STALE:
            payload["stale"] = True
        if conflict:
            payload["conflict"] = conflict
        return payload
