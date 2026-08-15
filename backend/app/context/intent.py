"""What kind of question is this, and therefore what context is worth gathering.

Deliberately deterministic, like :mod:`app.mission.detection` — no model call.
Two reasons, both from earlier phases: an LLM round trip to decide whether to
do an LLM round trip is latency nobody asked for, and §12 requires that "what's
my battery?" not trigger a workspace scan. A regex that is occasionally wrong
and always fast is the right trade here, and being wrong only ever means
gathering the ordinary amount of context.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import StrEnum


class Intent(StrEnum):
    CONTINUE = "CONTINUE"
    """"Continue where I left off." Needs the fullest picture NEXUS can build."""

    WHAT_CHANGED = "WHAT_CHANGED"
    """"What changed?" Answered from Git evidence, not from memory."""

    ORIENT = "ORIENT"
    """"What am I working on?" Workspace plus memory, no diffing."""

    RECALL = "RECALL"
    """"What do you remember?" Memory only — no filesystem work at all."""

    INVESTIGATE = "INVESTIGATE"
    """"Investigate this." The observation is the starting point, and the
    workspace and processes are where the evidence lives."""

    RECENT = "RECENT"
    """"What happened recently?" Answered from what NEXUS already noticed —
    the observations are the evidence, so no fresh inspection is needed."""

    GENERAL = "GENERAL"
    """Anything else. Gathers the ordinary, cheap context."""


@dataclass(frozen=True, slots=True)
class ContextPlan:
    """Which collectors to run for one request.

    Every flag defaults to off: context gathering is opt-in per intent, so a
    new intent cannot accidentally inherit an expensive scan.
    """

    intent: Intent
    memories: bool = False
    workspace: bool = False
    git_history: bool = False
    processes: bool = False
    machine: bool = False
    observations: bool = False

    @property
    def gathers_anything(self) -> bool:
        return any(
            (
                self.memories, self.workspace, self.git_history, self.processes,
                self.machine, self.observations,
            )
        )


_PATTERNS: tuple[tuple[Intent, re.Pattern[str]], ...] = (
    (
        Intent.CONTINUE,
        re.compile(
            r"\b(continue|resume|pick up|carry on)\b|"
            r"\bwhere (?:i|we) (?:left off|got to)\b|"
            r"\bleft off\b"
        ),
    ),
    (
        Intent.WHAT_CHANGED,
        re.compile(
            r"\bwhat (?:has |have )?(?:changed|i changed|we changed)\b|"
            r"\bwhat did (?:i|we) (?:change|do|work on)\b|"
            r"\b(?:changed|different) since\b|"
            r"\bmy (?:recent )?changes\b|"
            r"\bwhat'?s (?:changed|different)\b"
        ),
    ),
    (
        Intent.ORIENT,
        re.compile(
            r"\bwhat (?:am|was) i (?:working on|doing)\b|"
            r"\bwhat project\b|"
            r"\bwhere (?:am|was) i working\b|"
            r"\bwhich project\b|"
            r"\bwhat (?:is|'s) my current (?:project|workspace)\b"
        ),
    ),
    (
        Intent.INVESTIGATE,
        re.compile(
            r"\binvestigate\b|"
            r"\bwhy did (?:it|this|that|the \w+) (?:crash|fail|stop|die|exit)\b|"
            r"\blook into (?:this|it|that)\b|"
            r"\bcheck (?:this|it) out\b|"
            r"\bwhat went wrong\b"
        ),
    ),
    (
        Intent.RECENT,
        re.compile(
            r"\bwhat happened\b|"
            r"\banything (?:happen|change|break|go wrong)\b|"
            r"\bwhat did i miss\b|"
            r"\bcatch me up\b|"
            r"\bwhat have you noticed\b|"
            r"\bany (?:problems|issues|errors|alerts)\b"
        ),
    ),
    (
        Intent.RECALL,
        re.compile(
            r"\bwhat do you (?:remember|know) about\b|"
            r"\bshow me what you remember\b|"
            r"\bwhat do you remember\b|"
            r"\bwhat have you remembered\b|"
            r"\byour memor(?:y|ies)\b"
        ),
    ),
)

#: What each intent is allowed to gather. `GENERAL` deliberately does not touch
#: the filesystem: an ordinary question ("what's my battery?") should cost one
#: tool call, and the agent can still reach for any SAFE tool itself.
_PLANS: dict[Intent, ContextPlan] = {
    Intent.CONTINUE: ContextPlan(
        Intent.CONTINUE,
        memories=True,
        workspace=True,
        git_history=True,
        processes=True,
        machine=False,
    ),
    Intent.WHAT_CHANGED: ContextPlan(
        Intent.WHAT_CHANGED, memories=False, workspace=True, git_history=True
    ),
    Intent.ORIENT: ContextPlan(
        Intent.ORIENT, memories=True, workspace=True, processes=True
    ),
    Intent.RECALL: ContextPlan(Intent.RECALL, memories=True),
    # Answered from the activity feed. Deliberately no live inspection: the
    # question is about what already happened, and re-scanning now would
    # describe the present rather than the recent past.
    Intent.RECENT: ContextPlan(Intent.RECENT, observations=True),
    # The observation says what happened; the live state says whether it is
    # still true. An investigation needs both, and no Git history.
    Intent.INVESTIGATE: ContextPlan(
        Intent.INVESTIGATE, observations=True, processes=True, workspace=True,
        memories=True,
    ),
    Intent.GENERAL: ContextPlan(Intent.GENERAL, memories=True),
}


#: What a mission planner gets, regardless of how the objective is phrased.
#: Planning a multi-step objective needs to know where the work happens and
#: what the machine is, so this deliberately does not depend on the intent
#: classifier — a mission is already known to be substantial.
MISSION_PLAN = ContextPlan(
    Intent.GENERAL,
    memories=True,
    workspace=True,
    processes=True,
    machine=True,
    observations=True,
)


#: What the context panel gathers: where the user is and what is running,
#: without the Git history a "what changed?" question would need.
ORIENT_PLAN = _PLANS[Intent.ORIENT]


def classify(message: str) -> Intent:
    """Which of the known shapes this message takes."""
    text = (message or "").strip().casefold()
    if not text:
        return Intent.GENERAL
    for intent, pattern in _PATTERNS:
        if pattern.search(text):
            return intent
    return Intent.GENERAL


def plan_for(message: str) -> ContextPlan:
    """The context plan for one user message."""
    return _PLANS[classify(message)]


__all__ = ["MISSION_PLAN", "ORIENT_PLAN", "ContextPlan", "Intent", "classify", "plan_for"]
