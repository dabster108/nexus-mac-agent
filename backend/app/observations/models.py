"""What an observation is, and what it is allowed to contain.

An observation is *not* a memory. A memory answers "what should NEXUS
remember?"; an observation answers "what just happened?" — it is disposable,
bounded, and never authoritative.

Every field here is built from untrusted input: a Git branch someone named, a
filename, a line of process output, the body a local service returned. So the
sanitising in this module is not decoration. Text is redacted, flattened to a
single line and truncated *at construction*, which means there is no path that
puts raw process output into an observation and no second place to remember to
do it.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any
from uuid import uuid4

# --- bounds ----------------------------------------------------------------

#: Newest-wins ring. Two hundred is far more than anyone reads and small enough
#: that a pathological detector cannot grow the process.
MAX_OBSERVATIONS = 200
MAX_TITLE_CHARS = 120
MAX_SUMMARY_CHARS = 400
MAX_EVIDENCE_CHARS = 600
MAX_EVIDENCE_FIELDS = 8


class Category(StrEnum):
    PROCESS = "PROCESS"
    SERVICE = "SERVICE"
    WORKSPACE = "WORKSPACE"
    GIT = "GIT"
    MEMORY = "MEMORY"
    MISSION = "MISSION"
    TASK = "TASK"
    APPROVAL = "APPROVAL"
    SYSTEM = "SYSTEM"


class Severity(StrEnum):
    INFO = "INFO"
    NOTICE = "NOTICE"
    WARNING = "WARNING"
    ERROR = "ERROR"


# --- sanitising ------------------------------------------------------------

#: Credential shapes worth catching in process output. Deliberately a short,
#: high-signal list rather than a scanner: the real protection is that
#: observations quote very little output at all.
_SECRET_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"\b(gh[pousr]_[A-Za-z0-9]{16,})"),
    re.compile(r"\b(sk-[A-Za-z0-9-]{16,})"),
    re.compile(r"\b(xox[baprs]-[A-Za-z0-9-]{10,})"),
    re.compile(r"\b(AKIA[0-9A-Z]{12,})"),
    re.compile(r"\b(gsk_[A-Za-z0-9]{16,})"),
    re.compile(r"\b(eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{5,})"),
    # `TOKEN=...`, `api_key: ...` and friends: the name is the giveaway.
    re.compile(
        r"((?:password|passwd|secret|token|api[_-]?key|access[_-]?key|"
        r"private[_-]?key|credential)s?\s*[:=]\s*)(\S+)",
        re.I,
    ),
    re.compile(r"(://[^/\s:@]+:)([^@\s]+)(@)"),  # user:pass@host
)

REDACTED = "[redacted]"

#: Control characters, which is how text smuggles in fake structure.
_CONTROL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")


def redact(text: str) -> str:
    """Blank out anything credential-shaped."""
    for pattern in _SECRET_PATTERNS:
        if pattern.groups >= 3:
            text = pattern.sub(rf"\1{REDACTED}\3", text)
        elif pattern.groups == 2:
            text = pattern.sub(rf"\1{REDACTED}", text)
        else:
            text = pattern.sub(REDACTED, text)
    return text


def clean(text: Any, limit: int) -> str:
    """Redacted, single-line, bounded.

    Flattening newlines matters as much as truncating: a line of process output
    beginning "SYSTEM:" reads very differently when it cannot start a line of
    its own in whatever renders it.
    """
    if text is None:
        return ""
    value = _CONTROL.sub("", str(text))
    value = redact(value)
    value = " ".join(value.split())
    if len(value) > limit:
        value = value[: limit - 1].rstrip() + "…"
    return value


def _clean_evidence(evidence: dict[str, Any] | None) -> dict[str, Any]:
    """Evidence is quoted machine state, so it is bounded field by field."""
    if not evidence:
        return {}
    out: dict[str, Any] = {}
    for key, value in list(evidence.items())[:MAX_EVIDENCE_FIELDS]:
        name = clean(key, 40)
        if isinstance(value, bool) or isinstance(value, int) or value is None:
            out[name] = value
        else:
            out[name] = clean(value, MAX_EVIDENCE_CHARS // MAX_EVIDENCE_FIELDS)
    return out


def new_observation_id() -> str:
    return f"obs_{uuid4().hex[:12]}"


def _now() -> str:
    return datetime.now(UTC).isoformat()


@dataclass(frozen=True, slots=True)
class Observation:
    """One thing NEXUS noticed. Sanitised on the way in, never on the way out."""

    category: Category
    severity: Severity
    title: str
    summary: str = ""
    source: str = "detector"
    evidence: dict[str, Any] = field(default_factory=dict)
    workspace: str | None = None
    related_process_id: str | None = None
    related_task_id: str | None = None
    related_memory_id: str | None = None
    #: Whether "Investigate" is worth offering. A recovery is not a problem.
    actionable: bool = False
    observation_id: str = field(default_factory=new_observation_id)
    created_at: str = field(default_factory=_now)
    dismissed: bool = False
    #: Groups repeats of the same condition, so a flapping service updates one
    #: observation instead of producing a new one every check.
    dedupe_key: str = ""

    @classmethod
    def build(
        cls,
        *,
        category: Category,
        severity: Severity,
        title: str,
        summary: str = "",
        source: str = "detector",
        evidence: dict[str, Any] | None = None,
        workspace: str | None = None,
        related_process_id: str | None = None,
        related_task_id: str | None = None,
        related_memory_id: str | None = None,
        actionable: bool = False,
        dedupe_key: str = "",
    ) -> Observation:
        """The only supported way to make one, so nothing skips sanitising."""
        return cls(
            category=category,
            severity=severity,
            title=clean(title, MAX_TITLE_CHARS),
            summary=clean(summary, MAX_SUMMARY_CHARS),
            source=clean(source, 40),
            evidence=_clean_evidence(evidence),
            workspace=clean(workspace, 200) or None,
            related_process_id=clean(related_process_id, 60) or None,
            related_task_id=clean(related_task_id, 60) or None,
            related_memory_id=clean(related_memory_id, 60) or None,
            actionable=actionable,
            dedupe_key=dedupe_key or f"{category}:{clean(title, 60)}",
        )

    def to_public_dict(self) -> dict[str, Any]:
        return {
            "observation_id": self.observation_id,
            "category": str(self.category),
            "severity": str(self.severity),
            "title": self.title,
            "summary": self.summary,
            "source": self.source,
            "evidence": self.evidence,
            "workspace": self.workspace,
            "related_process_id": self.related_process_id,
            "related_task_id": self.related_task_id,
            "related_memory_id": self.related_memory_id,
            "actionable": self.actionable,
            "dismissed": self.dismissed,
            "created_at": self.created_at,
        }

    def to_line(self) -> str:
        """One line for "what happened recently?". Still quoted data."""
        where = f" [{self.workspace}]" if self.workspace else ""
        return f"- {self.created_at[11:19]} ({self.severity}) {self.title}{where}: {self.summary}"


__all__ = [
    "MAX_EVIDENCE_CHARS",
    "MAX_OBSERVATIONS",
    "MAX_SUMMARY_CHARS",
    "MAX_TITLE_CHARS",
    "REDACTED",
    "Category",
    "Observation",
    "Severity",
    "clean",
    "new_observation_id",
    "redact",
]
