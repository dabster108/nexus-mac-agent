"""What an execution trace is.

The trace is a **projection**, not a record: every entry corresponds to an
``ExecutionEvent`` that actually fired, or to a piece of structured state the
system already holds. Nothing here is reconstructed, and nothing is generated
by a model — the one rule that makes an audit trail worth reading is that it
cannot be more optimistic than what happened.

Two things this deliberately cannot represent:

* **Model reasoning.** There is no field for it, so there is no path by which
  hidden chain-of-thought reaches a trace.
* **Certainty about influence.** The trace can prove context was *provided to
  the agent*; it cannot prove the model used it. The wording throughout says
  the former, because the honest sentence is the one worth showing.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from app.observations.models import clean

# --- bounds ----------------------------------------------------------------

MAX_TRACE_ITEMS = 60
MAX_TRACE_CHARS = 400
MAX_EVIDENCE_PER_TRACE = 12
MAX_TRACES = 100


class Phase:
    """Where a step sits in the request's life. Plain strings: the frontend
    groups by these, and an enum would need mirroring there for no gain."""

    CONTEXT = "CONTEXT"
    ACTION = "ACTION"
    APPROVAL = "APPROVAL"
    VERIFICATION = "VERIFICATION"
    OUTCOME = "OUTCOME"
    MISSION = "MISSION"


class Mark:
    """How a step reads at a glance."""

    OK = "ok"
    """It happened and it worked."""

    FAILED = "failed"
    WAITING = "waiting"
    """Stopped for a person."""

    DENIED = "denied"
    INFO = "info"
    """It happened; there is nothing to pass or fail."""

    SKIPPED = "skipped"


@dataclass(frozen=True, slots=True)
class TraceStep:
    """One thing that actually happened."""

    phase: str
    label: str
    mark: str = Mark.INFO
    detail: str = ""
    #: Why this step occurred, from a deterministic rule — never from a model.
    reason: str = ""
    tool: str | None = None
    timestamp: str = ""

    @classmethod
    def build(
        cls,
        *,
        phase: str,
        label: str,
        mark: str = Mark.INFO,
        detail: str = "",
        reason: str = "",
        tool: str | None = None,
        timestamp: str = "",
    ) -> TraceStep:
        """The only constructor, so nothing skips sanitising.

        Labels and details quote tool output and workspace metadata, which is
        written by something other than NEXUS.
        """
        return cls(
            phase=phase,
            label=clean(label, MAX_TRACE_CHARS),
            mark=mark,
            detail=clean(detail, MAX_TRACE_CHARS),
            reason=clean(reason, MAX_TRACE_CHARS),
            tool=clean(tool, 60) or None,
            timestamp=timestamp,
        )

    def to_public_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "phase": self.phase,
            "label": self.label,
            "mark": self.mark,
        }
        for name in ("detail", "reason", "tool", "timestamp"):
            value = getattr(self, name)
            if value:
                payload[name] = value
        return payload


@dataclass(frozen=True, slots=True)
class ContextItem:
    """One thing that was gathered, and whether it reached the agent.

    ``used`` is deliberately named for what can be proven: the item was put in
    front of the model. Whether the model's answer depended on it is not
    observable from here, and the frontend says "provided to the agent"
    accordingly.
    """

    kind: str
    label: str
    provided: bool
    detail: str = ""
    reason: str = ""

    @classmethod
    def build(
        cls, *, kind: str, label: str, provided: bool, detail: str = "", reason: str = ""
    ) -> ContextItem:
        return cls(
            kind=kind,
            label=clean(label, 120),
            provided=provided,
            detail=clean(detail, MAX_TRACE_CHARS),
            reason=clean(reason, MAX_TRACE_CHARS),
        )

    def to_public_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "kind": self.kind,
            "label": self.label,
            "provided": self.provided,
        }
        if self.detail:
            payload["detail"] = self.detail
        if self.reason:
            payload["reason"] = self.reason
        return payload


@dataclass(frozen=True, slots=True)
class EvidenceItem:
    """One observed fact behind an outcome, carried through from Phase 13."""

    statement: str
    source: str = ""
    kind: str = "OBSERVED"
    confidence: str = "HIGH"

    @classmethod
    def build(cls, **kwargs: Any) -> EvidenceItem:
        return cls(
            statement=clean(kwargs.get("statement", ""), MAX_TRACE_CHARS),
            source=clean(kwargs.get("source", ""), 60),
            kind=str(kwargs.get("kind") or "OBSERVED"),
            confidence=str(kwargs.get("confidence") or "HIGH"),
        )

    def to_public_dict(self) -> dict[str, Any]:
        return {
            "statement": self.statement,
            "source": self.source,
            "kind": self.kind,
            "confidence": self.confidence,
        }


@dataclass(frozen=True, slots=True)
class Trace:
    """The whole story of one request, derived from what actually happened.

    ``summary`` and ``outcome_reason`` are composed from evidence, which means
    they quote tool output — so they are sanitised here as well as upstream.
    Defence in depth on purpose: the trace should not be safe only because
    something else remembered to clean its input.
    """

    task_id: str
    request: str
    status: str
    #: One plain sentence, composed from the steps by a deterministic rule.
    summary: str = ""
    context: tuple[ContextItem, ...] = ()
    steps: tuple[TraceStep, ...] = ()
    evidence: tuple[EvidenceItem, ...] = ()
    outcome: str | None = None
    outcome_reason: str = ""
    created_at: str = ""
    completed_at: str | None = None

    def to_public_dict(self) -> dict[str, Any]:
        return {
            "task_id": self.task_id,
            "request": clean(self.request, MAX_TRACE_CHARS),
            "status": self.status,
            "summary": clean(self.summary, MAX_TRACE_CHARS),
            "context": [c.to_public_dict() for c in self.context],
            "steps": [s.to_public_dict() for s in self.steps[:MAX_TRACE_ITEMS]],
            "evidence": [e.to_public_dict() for e in self.evidence[:MAX_EVIDENCE_PER_TRACE]],
            "outcome": self.outcome,
            "outcome_reason": clean(self.outcome_reason, MAX_TRACE_CHARS),
            "created_at": self.created_at,
            "completed_at": self.completed_at,
        }


__all__ = [
    "MAX_EVIDENCE_PER_TRACE",
    "MAX_TRACES",
    "MAX_TRACE_CHARS",
    "MAX_TRACE_ITEMS",
    "ContextItem",
    "EvidenceItem",
    "Mark",
    "Phase",
    "Trace",
    "TraceStep",
]
