"""The mission and step model.

A :class:`Task` (``app.agent.tasks``) is one execution lifecycle — a single
request in, a single result out. A :class:`Mission` is bigger: a multi-step
objective that runs several tasks, one per step, in sequence. This module only
defines the shape; :mod:`app.mission.engine` is what runs one.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any
from uuid import uuid4


class MissionStatus(StrEnum):
    PLANNING = "PLANNING"
    READY = "READY"
    RUNNING = "RUNNING"
    WAITING_APPROVAL = "WAITING_APPROVAL"
    PAUSED = "PAUSED"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"

    @property
    def is_terminal(self) -> bool:
        return self in (
            MissionStatus.COMPLETED,
            MissionStatus.FAILED,
            MissionStatus.CANCELLED,
        )


class StepStatus(StrEnum):
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    WAITING_APPROVAL = "WAITING_APPROVAL"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    SKIPPED = "SKIPPED"
    CANCELLED = "CANCELLED"

    @property
    def is_terminal(self) -> bool:
        return self in (
            StepStatus.COMPLETED,
            StepStatus.FAILED,
            StepStatus.SKIPPED,
            StepStatus.CANCELLED,
        )


#: When a step may run, relative to the outcome of its ``depends_on`` steps.
#: "always" still waits for dependencies to *finish* — it does not mean
#: unconditional from the start — it only ignores whether they succeeded.
RunCondition = str  # Literal["always", "on_success", "on_failure"]


def new_mission_id() -> str:
    return f"mission_{uuid4().hex[:12]}"


def _now() -> str:
    return datetime.now(UTC).isoformat()


@dataclass
class MissionStep:
    """One planned action: a tool, in a specific role within the mission."""

    id: str
    description: str
    tool: str
    arguments: dict[str, Any] = field(default_factory=dict)
    depends_on: tuple[str, ...] = ()
    run_if: RunCondition = "always"
    status: StepStatus = StepStatus.PENDING
    task_id: str | None = None
    """The Task this step ran as, once it has started. Inspectable via the
    ordinary ``GET /api/tasks/{task_id}``."""
    result_message: str | None = None
    retries: int = 0

    #: Whether the *tool* ran. Distinct from `outcome`, which is whether the
    #: step's goal was met: a start_process that launches a process which then
    #: dies has action SUCCESS and outcome FAILED.
    action_status: str | None = None
    verification_status: str | None = None
    outcome: str | None = None
    evidence: tuple[str, ...] = ()

    def to_public_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "id": self.id,
            "description": self.description,
            "tool": self.tool,
            "status": str(self.status),
        }
        for name in ("action_status", "verification_status", "outcome"):
            value = getattr(self, name)
            if value:
                payload[name] = value
        if self.evidence:
            payload["evidence"] = list(self.evidence[:4])
        if self.depends_on:
            payload["depends_on"] = list(self.depends_on)
        if self.run_if != "always":
            payload["run_if"] = self.run_if
        if self.task_id:
            payload["task_id"] = self.task_id
        return payload


@dataclass
class Mission:
    """A multi-step objective and its execution state."""

    id: str
    objective: str
    task_id: str
    status: MissionStatus = MissionStatus.PLANNING
    steps: list[MissionStep] = field(default_factory=list)
    context: dict[str, Any] = field(default_factory=dict)
    """Small facts carried between steps — a detected project path, a started
    process's id, a service URL — so later steps do not have to re-derive or
    guess what an earlier step already found. Deliberately generic (a handful
    of well-known keys, not a general memory system)."""
    created_at: str = field(default_factory=_now)
    updated_at: str = field(default_factory=_now)
    completed_at: str | None = None
    failure_reason: str | None = None
    tool_call_count: int = 0

    def step(self, step_id: str) -> MissionStep:
        for step in self.steps:
            if step.id == step_id:
                return step
        raise KeyError(step_id)

    def summary(self) -> dict[str, Any]:
        completed = sum(1 for s in self.steps if s.status is StepStatus.COMPLETED)
        skipped = sum(1 for s in self.steps if s.status is StepStatus.SKIPPED)
        failed = sum(1 for s in self.steps if s.status is StepStatus.FAILED)
        cancelled = sum(1 for s in self.steps if s.status is StepStatus.CANCELLED)
        return {
            "mission_id": self.id,
            "objective": self.objective,
            "status": str(self.status),
            "steps_total": len(self.steps),
            "steps_completed": completed,
            "steps_skipped": skipped,
            "steps_failed": failed,
            "steps_cancelled": cancelled,
            "steps": [step.to_public_dict() for step in self.steps],
            "failure_reason": self.failure_reason,
        }
