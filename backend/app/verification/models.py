"""What an outcome is, and what counts as evidence for one.

The distinction this whole phase turns on: *the tool returned success* and
*the user's goal was achieved* are different claims, and only the first one is
free. `start_process` returning ``success: true`` proves a process was
launched — not that it is still alive, and certainly not that it is serving.

So an outcome is never asserted; it is *derived* from evidence, and the
evidence records where it came from. An item that a tool reported is
``OBSERVED``. An item that follows from reasoning over observations is
``INFERRED`` and is never allowed to carry HIGH confidence on its own. The
model does not produce evidence at all.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from app.observations.models import clean

# --- bounds ----------------------------------------------------------------

MAX_EVIDENCE_ITEMS = 8
MAX_EVIDENCE_CHARS = 400
MAX_VERIFICATION_STEPS = 3
MAX_VERIFICATION_TOOL_CALLS = 5
MAX_VERIFICATION_RUNTIME_SECONDS = 10.0


class Outcome(StrEnum):
    SUCCESS = "SUCCESS"
    """The operation completed *and* evidence confirms the intended result."""

    PARTIAL_SUCCESS = "PARTIAL_SUCCESS"
    """It completed, but only part of the intended result could be confirmed."""

    FAILED = "FAILED"
    """It failed, or evidence proves the intended result did not happen."""

    UNKNOWN = "UNKNOWN"
    """It completed and there is not enough evidence either way. The honest
    answer whenever verification is impossible, refused, or out of budget —
    and always preferable to an invented SUCCESS."""


class Kind(StrEnum):
    OBSERVED = "OBSERVED"
    """A tool said this. The only kind that may be HIGH."""

    INFERRED = "INFERRED"
    """This follows from observations. Capped at MEDIUM by construction."""


class Confidence(StrEnum):
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"


def _now() -> str:
    return datetime.now(UTC).isoformat()


@dataclass(frozen=True, slots=True)
class Evidence:
    """One fact behind an outcome.

    ``statement`` is sanitised on construction because much of it quotes tool
    output — a process's own stderr, a service's response — which is written
    by something other than NEXUS and must not be able to fabricate structure.
    """

    source: str
    statement: str
    kind: Kind = Kind.OBSERVED
    confidence: Confidence = Confidence.HIGH
    timestamp: str = field(default_factory=_now)

    @classmethod
    def observed(
        cls, source: str, statement: str, confidence: Confidence = Confidence.HIGH
    ) -> Evidence:
        return cls(
            source=clean(source, 40),
            statement=clean(statement, MAX_EVIDENCE_CHARS),
            kind=Kind.OBSERVED,
            confidence=confidence,
        )

    @classmethod
    def inferred(cls, source: str, statement: str) -> Evidence:
        """An inference can never be more than MEDIUM, whoever asks."""
        return cls(
            source=clean(source, 40),
            statement=clean(statement, MAX_EVIDENCE_CHARS),
            kind=Kind.INFERRED,
            confidence=Confidence.MEDIUM,
        )

    def to_public_dict(self) -> dict[str, Any]:
        return {
            "source": self.source,
            "statement": self.statement,
            "kind": str(self.kind),
            "confidence": str(self.confidence),
            "timestamp": self.timestamp,
        }

    def to_line(self) -> str:
        marker = "" if self.kind is Kind.OBSERVED else " (inferred)"
        return f"- {self.statement}{marker}"


@dataclass(frozen=True, slots=True)
class Verification:
    """The result of checking whether an action achieved what was asked."""

    tool: str
    outcome: Outcome
    evidence: tuple[Evidence, ...] = ()
    #: One plain sentence, composed from the evidence — never by a model.
    summary: str = ""
    #: What could not be established. Named so the answer can say so.
    unknowns: tuple[str, ...] = ()
    duration_ms: float = 0.0
    tool_calls: int = 0

    @property
    def observed(self) -> tuple[Evidence, ...]:
        return tuple(e for e in self.evidence if e.kind is Kind.OBSERVED)

    def to_public_dict(self) -> dict[str, Any]:
        return {
            "tool": self.tool,
            "outcome": str(self.outcome),
            "summary": self.summary,
            "evidence": [e.to_public_dict() for e in self.evidence[:MAX_EVIDENCE_ITEMS]],
            "unknowns": list(self.unknowns[:4]),
            "duration_ms": round(self.duration_ms, 1),
            "tool_calls": self.tool_calls,
        }

    def to_prompt_block(self) -> str:
        """What the model is told, so its answer matches what was checked.

        Deliberately structured as KNOWN / UNKNOWN rather than as a conclusion:
        the outcome is already decided here, and the model's job is to say it
        in a sentence, not to re-litigate it.
        """
        lines = [f"Verification of '{self.tool}': {self.outcome}."]
        observed = self.observed
        if observed:
            lines.append("KNOWN (each of these was reported by a tool):")
            lines.extend(e.to_line() for e in observed[:MAX_EVIDENCE_ITEMS])
        inferred = [e for e in self.evidence if e.kind is Kind.INFERRED]
        if inferred:
            lines.append("LIKELY (follows from the above, not directly checked):")
            lines.extend(e.to_line() for e in inferred[:3])
        if self.unknowns:
            lines.append("UNKNOWN:")
            lines.extend(f"- {u}" for u in self.unknowns[:4])
        lines.append(
            "Report this outcome as it stands. Do not describe an unverified "
            "result as confirmed, and do not upgrade UNKNOWN to success."
        )
        return "\n".join(lines)


def unknown(tool: str, reason: str) -> Verification:
    """The honest default whenever nothing could be established."""
    return Verification(
        tool=tool,
        outcome=Outcome.UNKNOWN,
        summary="The action completed, but the result could not be verified.",
        unknowns=(clean(reason, 200),),
    )


__all__ = [
    "MAX_EVIDENCE_CHARS",
    "MAX_EVIDENCE_ITEMS",
    "MAX_VERIFICATION_RUNTIME_SECONDS",
    "MAX_VERIFICATION_STEPS",
    "MAX_VERIFICATION_TOOL_CALLS",
    "Confidence",
    "Evidence",
    "Kind",
    "Outcome",
    "Verification",
    "unknown",
]
