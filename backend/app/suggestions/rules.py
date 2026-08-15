"""Observation → suggestion. Pure functions, no I/O, no model, no tools.

Two jobs, both deterministic. First, deciding whether an observation is worth
saying anything about at all: a process starting is news, but it is not a
suggestion, and a suggestion for every observation is how a proactive
assistant becomes a nagging one. Second, composing the sentence that accepting
it will send.

That sentence matters more than it looks. It is the whole bridge between
"NEXUS noticed" and "the agent acts", and it is written here — once, in code —
rather than assembled in the frontend, so what accepting a suggestion asks for
cannot drift from what the suggestion said.
"""

from __future__ import annotations

from typing import Any

from app.observations.models import Category as ObservationCategory
from app.observations.models import Observation, Severity
from app.suggestions.models import Category, SuggestedAction, Suggestion

#: An investigation must not become a change. Every generated prompt says so
#: explicitly, because the cheapest way to keep "investigate" read-only is to
#: ask for it in the sentence the model actually receives.
READ_ONLY = "Do not change anything — just tell me what you find."

#: A workspace with fewer changes than this is ordinary work, not a nudge.
DIRTY_THRESHOLD = 10

#: Restarts within the store's memory before it stops looking like bad luck.
FLAPPING_THRESHOLD = 3

#: A development server left running longer than this is worth a mention.
LONG_RUNNING_SECONDS = 6 * 3600


def _process_name(observation: Observation) -> str:
    return observation.title.split(" failed")[0].split(" stopped")[0].strip() or "the process"


def from_observation(
    observation: Observation, *, repeats: int = 1
) -> Suggestion | None:
    """The suggestion this observation earns, if any."""
    if observation.category is ObservationCategory.PROCESS:
        return _from_process(observation, repeats)
    if observation.category is ObservationCategory.SERVICE:
        return _from_service(observation)
    if observation.category is ObservationCategory.GIT:
        return _from_git(observation)
    if observation.category is ObservationCategory.MEMORY:
        return _from_memory(observation)
    if observation.category is ObservationCategory.TASK:
        return _from_task(observation)
    return None


def _from_process(observation: Observation, repeats: int) -> Suggestion | None:
    # A process starting is good news; there is nothing to suggest about it.
    if not observation.actionable:
        return None

    name = _process_name(observation)
    process_id = observation.related_process_id
    exit_code = observation.evidence.get("exit_code")

    if repeats >= FLAPPING_THRESHOLD:
        return Suggestion.build(
            category=Category.PROCESS,
            severity=Severity.WARNING,
            title=f"{name} keeps stopping",
            description=f"It has stopped {repeats} times. Something is failing repeatedly.",
            reason="A process that restarts this often usually has a cause worth finding.",
            action=SuggestedAction(
                intent="investigate_process",
                process_id=process_id,
                prompt=(
                    f"The process {process_id} has stopped {repeats} times. Read its "
                    f"logs and status and tell me why it keeps failing. {READ_ONLY}"
                ),
            ),
            key=f"process:{process_id}:flapping",
            observation_id=observation.observation_id,
        )

    detail = f" with exit code {exit_code}" if exit_code is not None else ""
    return Suggestion.build(
        category=Category.PROCESS,
        severity=observation.severity,
        title=observation.title,
        description=f"The process stopped{detail}.",
        reason="Its logs will usually say why.",
        action=SuggestedAction(
            intent="investigate_process",
            process_id=process_id,
            workspace=observation.workspace,
            prompt=(
                f"Investigate process {process_id}: read its logs and status and tell "
                f"me why it stopped. {READ_ONLY}"
            ),
        ),
        key=f"process:{process_id}:stopped",
        observation_id=observation.observation_id,
    )


def _from_service(observation: Observation) -> Suggestion | None:
    if not observation.actionable:  # a recovery needs no suggestion
        return None
    url = observation.evidence.get("url") or "the service"
    name = observation.title.split(" became")[0].strip() or "A service"
    return Suggestion.build(
        category=Category.SERVICE,
        severity=Severity.WARNING,
        title=observation.title,
        description=f"Nothing answered at {url}.",
        reason="It may have stopped, or it may never have started.",
        action=SuggestedAction(
            intent="investigate_service",
            prompt=(
                f"{name} is unreachable at {url}. Check whether anything is running "
                f"for it and tell me what you find. {READ_ONLY}"
            ),
        ),
        key=f"service:{url}:down",
        observation_id=observation.observation_id,
    )


def _from_git(observation: Observation) -> Suggestion | None:
    changed = observation.evidence.get("changed_files")
    if not isinstance(changed, int) or changed < DIRTY_THRESHOLD:
        return None
    path = observation.workspace or observation.evidence.get("path") or "your workspace"
    return Suggestion.build(
        category=Category.WORKSPACE,
        severity=Severity.INFO,
        title=f"{changed} uncommitted changes",
        description=f"{path} has accumulated a lot of uncommitted work.",
        reason="A summary is easier to review than a long diff.",
        action=SuggestedAction(
            intent="review_changes",
            workspace=str(path),
            prompt=(
                f"Summarise the uncommitted changes in {path} — what has been "
                f"modified and roughly what changed. {READ_ONLY}"
            ),
        ),
        key=f"workspace:{path}:dirty",
        observation_id=observation.observation_id,
    )


def _from_memory(observation: Observation) -> Suggestion | None:
    memory_id = observation.related_memory_id
    stored = observation.evidence.get("stored")
    observed = observation.evidence.get("observed")
    if stored is None or observed is None:
        return None
    return Suggestion.build(
        category=Category.MEMORY,
        severity=Severity.WARNING,
        title="A remembered fact looks out of date",
        description=f"You have {stored} saved, but {observed} is what is running.",
        reason="Updating it keeps later answers correct.",
        action=SuggestedAction(
            intent="update_memory",
            memory_key=str(observation.evidence.get("memory_id") or memory_id or ""),
            prompt=(
                f"What I remember says {stored}, but {observed} is what is actually "
                f"running. Update that memory to {observed}."
            ),
        ),
        key=f"memory:{memory_id}:outdated",
        observation_id=observation.observation_id,
    )


def _from_task(observation: Observation) -> Suggestion | None:
    if observation.severity is not Severity.ERROR:
        return None
    return Suggestion.build(
        category=Category.TASK,
        severity=Severity.NOTICE,
        title="A task failed",
        description=observation.summary or "The last request did not complete.",
        reason="It may have failed for a reason worth knowing.",
        action=SuggestedAction(
            intent="investigate_task",
            prompt=f"My last request failed. Tell me why, if you can. {READ_ONLY}",
        ),
        key=f"task:{observation.related_task_id}:failed",
        observation_id=observation.observation_id,
    )


# --- memory ------------------------------------------------------------------


def from_memory_statement(
    extracted: Any, *, workspace: str | None = None
) -> Suggestion | None:
    """Offer to remember a durable fact the user just stated.

    Never saves anything. Accepting sends "Remember that ..." to the ordinary
    chat path, where `save_memory` is CONFIRM and the user sees the value
    before it exists — two separate confirmations for one fact, deliberately:
    this one is "did I understand you", the second is "may I write it down".
    """
    if extracted is None:
        return None
    value = extracted.value or {}
    facts = {k: v for k, v in value.items() if k != "path"}
    if not facts:
        return None

    subject = extracted.key.replace("_", " ")
    readable = ", ".join(f"{k} {v}" for k, v in facts.items())
    # "my backend port is 8000" rather than "port 8000 for backend port".
    field, first = next(iter(facts.items()))
    sentence = f"my {subject} is {first}" if subject.endswith(field) else f"my {subject} {field} is {first}"

    return Suggestion.build(
        category=Category.MEMORY,
        severity=Severity.INFO,
        title=f"Remember your {subject}?",
        description=f"You described {readable} as how you usually work.",
        reason=extracted.reason,
        action=SuggestedAction(
            intent="save_memory",
            memory_key=extracted.key,
            workspace=workspace,
            prompt=f"Remember that {sentence}.",
        ),
        key=f"memory:remember:{extracted.key}",
    )


# --- long-running processes -------------------------------------------------


def long_running_process(process: dict[str, Any]) -> Suggestion | None:
    """A development server nobody has stopped in hours.

    Not an observation — nothing *changed* — which is exactly why it lives
    here: a suggestion can come from a standing condition as well as an event.
    """
    runtime = process.get("runtime_seconds")
    if not isinstance(runtime, (int, float)) or runtime < LONG_RUNNING_SECONDS:
        return None
    if str(process.get("status")) != "RUNNING":
        return None
    process_id = str(process.get("process_id") or "")
    name = process.get("label") or process.get("command") or "A process"
    hours = int(runtime // 3600)
    return Suggestion.build(
        category=Category.PROCESS,
        severity=Severity.INFO,
        title=f"{name} has been running for {hours} hours",
        description="It has been up for a long time.",
        reason="Long-lived development servers sometimes drift from the code on disk.",
        action=SuggestedAction(
            intent="inspect_process",
            process_id=process_id,
            prompt=(
                f"Process {process_id} has been running for {hours} hours. Check its "
                f"status and recent logs and tell me if it looks healthy. {READ_ONLY}"
            ),
        ),
        key=f"process:{process_id}:long_running",
    )


__all__ = [
    "DIRTY_THRESHOLD",
    "FLAPPING_THRESHOLD",
    "LONG_RUNNING_SECONDS",
    "READ_ONLY",
    "from_observation",
    "long_running_process",
]
