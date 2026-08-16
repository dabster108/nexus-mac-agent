"""Turning a verification into the things the rest of NEXUS already has.

Deliberately thin. An outcome is worth an observation when it changed
something a person would want to know about, and worth a suggestion when
there is a read-only next step. Both go through the existing stores, so the
existing dedupe, cooldown and rate limits apply unchanged — this module adds
no notification path of its own.
"""

from __future__ import annotations

from app.core.logging import get_logger
from app.observations.models import Category, Observation, Severity
from app.verification.models import Outcome, Verification

logger = get_logger(__name__)

#: The most recent verified outcome, kept so a follow-up ("why isn't it
#: working?") can be answered from what actually happened rather than from the
#: model's memory of the conversation. One entry, deliberately: this is the
#: *last* outcome, not a history, and observations already keep the record.
_LAST: dict[str, object] = {}


def remember_last(verification: Verification, request: str) -> None:
    _LAST["verification"] = verification
    _LAST["request"] = request


def last_outcome() -> tuple[Verification, str] | None:
    verification = _LAST.get("verification")
    if verification is None:
        return None
    return verification, str(_LAST.get("request") or "")


def forget_last() -> None:
    _LAST.clear()


def to_observation(
    verification: Verification, *, request: str, task_id: str, process_id: str | None = None
) -> Observation | None:
    """An observation, when the outcome is worth recording.

    A plain SUCCESS is not: the user asked for it and just watched it happen.
    A recovery, a failure or a partial result is, because those are the states
    someone would want to find later without having been present.
    """
    if verification.outcome is Outcome.UNKNOWN:
        return None

    if verification.outcome is Outcome.SUCCESS:
        # Only worth noting for things that *stay* true afterwards.
        if verification.tool != "start_process":
            return None
        return Observation.build(
            category=Category.PROCESS,
            severity=Severity.INFO,
            title="Started and verified",
            summary=verification.summary,
            evidence={"request": request, "checks": verification.tool_calls},
            related_task_id=task_id,
            related_process_id=process_id,
            actionable=False,
            dedupe_key=f"verify:{verification.tool}:{process_id}:ok",
        )

    severity = (
        Severity.ERROR if verification.outcome is Outcome.FAILED else Severity.NOTICE
    )
    return Observation.build(
        category=Category.PROCESS if process_id else Category.TASK,
        severity=severity,
        title=f"{verification.tool} did not achieve what was asked",
        summary=verification.summary,
        evidence={"outcome": str(verification.outcome), "request": request},
        related_task_id=task_id,
        related_process_id=process_id,
        actionable=True,
        dedupe_key=f"verify:{verification.tool}:{process_id or task_id}:{verification.outcome}",
    )


def record(
    verification: Verification,
    *,
    request: str,
    task_id: str,
    process_id: str | None = None,
) -> None:
    """Publish an outcome through the existing stores. Best-effort."""
    try:
        from app.observations.store import get_observation_store

        observation = to_observation(
            verification, request=request, task_id=task_id, process_id=process_id
        )
        if observation is not None:
            get_observation_store().record(observation)

        # No suggestion is offered here on purpose. Recording the observation
        # above already produces one through the Phase 12 engine, which
        # subscribes to the observation store — offering a second directly
        # produced two cards for one failure, which live testing caught.
        remember_last(verification, request)
    except Exception:  # noqa: BLE001 - reporting must not affect the run
        logger.warning("Could not record a verification outcome", exc_info=True)


__all__ = [
    "forget_last",
    "last_outcome",
    "record",
    "remember_last",
    "to_observation",
]
