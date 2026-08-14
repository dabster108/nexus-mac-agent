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

    def to_public_dict(self, *, stale: bool = False, conflict: str | None = None) -> dict[str, Any]:
        """The shape returned by the MCP tools.

        ``stale``/``conflict`` are supplied by the caller (the store computes
        staleness at read time; conflicts are detected by the context
        collector against live evidence) — neither is a column on this row.
        """
        payload: dict[str, Any] = {
            "id": self.id,
            "type": str(self.type),
            "key": self.key,
            "value": self.value,
            "source": str(self.source),
            "confidence": self.confidence,
            "status": str(self.status),
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }
        if stale:
            payload["stale"] = True
        if conflict:
            payload["conflict"] = conflict
        return payload
