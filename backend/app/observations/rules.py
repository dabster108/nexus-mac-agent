"""State transition → observation. Pure functions, no I/O, no model.

Every rule here takes a previous snapshot and a current one and returns what
changed. Keeping them pure is what makes "the detector is deterministic"
testable rather than aspirational: the whole decision surface can be exercised
without a Mac, a process, or a network.

The rules also decide what is *worth* saying. A process that is still running
is not news. A service that has been down for an hour is not news every ten
seconds. Only edges produce observations.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.observations.models import Category, Observation, Severity

# --- process ---------------------------------------------------------------

#: Statuses that mean the process is no longer doing its job.
_ENDED = {"STOPPED", "FAILED"}


def _describe_process(process: dict[str, Any]) -> str:
    label = process.get("label") or process.get("command") or "process"
    return str(label)


def process_transition(
    previous: dict[str, Any] | None, current: dict[str, Any]
) -> Observation | None:
    """What a managed process's change of status means."""
    process_id = str(current.get("process_id") or "")
    status = str(current.get("status") or "")
    before = str((previous or {}).get("status") or "")
    if not process_id or status == before:
        return None

    name = _describe_process(current)
    evidence = {
        "command": current.get("command"),
        "working_directory": current.get("working_directory"),
        "exit_code": current.get("exit_code"),
        "port": current.get("port"),
    }
    common = {
        "category": Category.PROCESS,
        "evidence": evidence,
        "workspace": current.get("working_directory"),
        "related_process_id": process_id,
        "dedupe_key": f"process:{process_id}:{status}",
    }

    if status == "FAILED":
        exit_code = current.get("exit_code")
        return Observation.build(
            severity=Severity.ERROR,
            title=f"{name} failed",
            summary=(
                f"The managed process stopped unexpectedly"
                + (f" with exit code {exit_code}." if exit_code is not None else ".")
            ),
            actionable=True,
            **common,
        )

    if status == "STOPPED" and before == "RUNNING":
        return Observation.build(
            severity=Severity.NOTICE,
            title=f"{name} stopped",
            summary="The managed process is no longer running.",
            actionable=True,
            **common,
        )

    if status == "RUNNING" and before in ("", "STARTING"):
        port = current.get("port")
        return Observation.build(
            severity=Severity.INFO,
            title=f"{name} started",
            summary=(
                f"Running on port {port}." if port else "The process is running."
            ),
            actionable=False,
            **common,
        )

    return None


def process_disappeared(previous: dict[str, Any]) -> Observation | None:
    """A process NEXUS was managing is no longer in the manager's list at all."""
    status = str(previous.get("status") or "")
    if status not in ("RUNNING", "STARTING"):
        return None
    process_id = str(previous.get("process_id") or "")
    name = _describe_process(previous)
    return Observation.build(
        category=Category.PROCESS,
        severity=Severity.WARNING,
        title=f"{name} disappeared",
        summary="A process NEXUS was managing is no longer being tracked.",
        evidence={
            "command": previous.get("command"),
            "working_directory": previous.get("working_directory"),
        },
        workspace=previous.get("working_directory"),
        related_process_id=process_id,
        actionable=True,
        dedupe_key=f"process:{process_id}:gone",
    )


# --- service ---------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ServiceState:
    """A registered local service and what it was last seen doing."""

    name: str
    url: str
    status: str = "UNKNOWN"  # UNKNOWN | UP | DOWN


def service_transition(
    service: ServiceState, reachable: bool, detail: str | None = None
) -> Observation | None:
    """Only the edges: UNKNOWN→UP, UP→DOWN, DOWN→UP."""
    status = "UP" if reachable else "DOWN"
    if status == service.status:
        return None

    common = {
        "category": Category.SERVICE,
        "evidence": {"url": service.url, "detail": detail},
        "dedupe_key": f"service:{service.name}:{status}",
    }

    if status == "DOWN":
        # UNKNOWN → DOWN is worth saying once: a service registered because the
        # user cares about it, which was never up, is a fact about now.
        return Observation.build(
            severity=Severity.WARNING,
            title=f"{service.name} became unreachable",
            summary=f"Nothing answered at {service.url}.",
            actionable=True,
            **common,
        )

    if service.status == "DOWN":
        return Observation.build(
            severity=Severity.INFO,
            title=f"{service.name} recovered",
            summary=f"{service.url} is answering again.",
            actionable=False,
            **common,
        )

    # UNKNOWN → UP on the first check is the expected state, not news.
    return None


# --- git / workspace -------------------------------------------------------


@dataclass(frozen=True, slots=True)
class GitState:
    """The part of a workspace's Git state worth watching."""

    path: str
    branch: str | None = None
    changed_files: int | None = None
    head: str | None = None


def git_transition(previous: GitState | None, current: GitState) -> Observation | None:
    """Branch switches, commits, and the tree becoming dirty or clean.

    A per-file event would be noise; the counts are what a person actually
    notices. Nothing here is inferred — every value came from ``git_status``.
    """
    if previous is None or previous.path != current.path:
        return None

    common = {
        "category": Category.GIT,
        "workspace": current.path,
        "dedupe_key": f"git:{current.path}",
    }

    if previous.branch != current.branch and current.branch:
        return Observation.build(
            severity=Severity.NOTICE,
            title=f"Branch changed to {current.branch}",
            summary=f"Was {previous.branch or 'unknown'}.",
            evidence={"path": current.path, "from": previous.branch, "to": current.branch},
            actionable=False,
            **{**common, "dedupe_key": f"git:{current.path}:branch:{current.branch}"},
        )

    if current.head and previous.head and current.head != previous.head:
        return Observation.build(
            severity=Severity.INFO,
            title="New commits",
            summary=f"The branch {current.branch or ''} has moved on.".strip(),
            evidence={"path": current.path, "head": current.head},
            actionable=False,
            **{**common, "dedupe_key": f"git:{current.path}:head:{current.head}"},
        )

    before = previous.changed_files
    after = current.changed_files
    if before is None or after is None or before == after:
        return None

    if after == 0:
        return Observation.build(
            severity=Severity.INFO,
            title="Working tree is clean",
            summary="All changes have been committed or reverted.",
            evidence={"path": current.path},
            actionable=False,
            **{**common, "dedupe_key": f"git:{current.path}:clean"},
        )

    if before == 0:
        return Observation.build(
            severity=Severity.INFO,
            title="Working tree has changes",
            summary=f"{after} file(s) are now modified.",
            evidence={"path": current.path, "changed_files": after},
            actionable=False,
            **{**common, "dedupe_key": f"git:{current.path}:dirty"},
        )

    delta = after - before
    direction = "additional" if delta > 0 else "fewer"
    return Observation.build(
        severity=Severity.INFO,
        title="Workspace changed",
        summary=f"{abs(delta)} {direction} file(s) modified ({after} in total).",
        evidence={"path": current.path, "changed_files": after},
        actionable=False,
        **{**common, "dedupe_key": f"git:{current.path}:count"},
    )


# --- memory ----------------------------------------------------------------


def memory_contradiction(
    memory_id: str, key: str, stored: Any, observed: Any, source: str
) -> Observation:
    """Phase 10 already detects these; this is the same fact as an observation.

    Deliberately WARNING rather than ERROR, and deliberately not a deletion:
    the memory may still be what the user wants, and only they can say.
    """
    return Observation.build(
        category=Category.MEMORY,
        severity=Severity.WARNING,
        title="A remembered fact may be out of date",
        summary=f"'{key}' says {stored}, but {source} reports {observed}.",
        evidence={"memory_id": memory_id, "stored": stored, "observed": observed,
                  "source": source},
        related_memory_id=memory_id,
        actionable=True,
        dedupe_key=f"memory:{memory_id}:contradiction",
    )


# --- task / mission --------------------------------------------------------

#: Only lifecycle endings become observations. Every other task event is
#: already on the timeline; duplicating them would make the activity feed a
#: second, noisier copy of it.
_TASK_OBSERVABLE = {"error", "cancelled"}


def task_outcome(
    task_id: str, request: str, status: str, message: str | None = None
) -> Observation | None:
    if status not in _TASK_OBSERVABLE:
        return None
    severity = Severity.ERROR if status == "error" else Severity.NOTICE
    title = "A task failed" if status == "error" else "A task was cancelled"
    return Observation.build(
        category=Category.TASK,
        severity=severity,
        title=title,
        summary=message or request,
        evidence={"request": request},
        related_task_id=task_id,
        actionable=status == "error",
        dedupe_key=f"task:{task_id}:{status}",
    )


def mission_outcome(
    task_id: str, objective: str, status: str, message: str | None = None
) -> Observation | None:
    if status not in ("completed", "failed", "cancelled"):
        return None
    severity = {
        "completed": Severity.INFO,
        "failed": Severity.ERROR,
        "cancelled": Severity.NOTICE,
    }[status]
    return Observation.build(
        category=Category.MISSION,
        severity=severity,
        title=f"Mission {status}",
        summary=message or objective,
        evidence={"objective": objective},
        related_task_id=task_id,
        actionable=status == "failed",
        dedupe_key=f"mission:{task_id}:{status}",
    )


def approval_waiting(task_id: str, tool: str, description: str) -> Observation:
    return Observation.build(
        category=Category.APPROVAL,
        severity=Severity.NOTICE,
        title="Approval needed",
        summary=description,
        evidence={"tool": tool},
        related_task_id=task_id,
        actionable=False,
        dedupe_key=f"approval:{task_id}:{tool}",
    )


__all__ = [
    "GitState",
    "ServiceState",
    "approval_waiting",
    "git_transition",
    "memory_contradiction",
    "mission_outcome",
    "process_disappeared",
    "process_transition",
    "service_transition",
    "task_outcome",
]
