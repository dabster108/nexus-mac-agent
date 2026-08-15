"""Deciding which memories are worth showing the model.

§7 rules out embeddings, which is a better fit than it first sounds: the
memory store is small, structured and keyed, so a handful of explicit signals
beats a similarity score nobody can debug. Every point a memory scores here
can be named — "the user said 'nexus' and this memory's key contains it" —
and that is what makes :func:`explain` possible, and the memory panel honest.

Scoring never *grants* anything. A memory that scores highly is still just a
hint the model must verify; precedence lives in the prompt block, not here.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from typing import Any

#: Words too common to say anything about which memory is relevant. Larger
#: than the collector's old list because scoring is more sensitive to noise
#: than a LIKE query was.
STOPWORDS: frozenset[str] = frozenset(
    {
        "the", "a", "an", "my", "me", "and", "or", "to", "of", "for", "in", "on",
        "at", "is", "it", "this", "that", "what", "whether", "tell", "check",
        "start", "stop", "run", "please", "then", "with", "about", "was", "were",
        "did", "do", "does", "am", "are", "you", "your", "i", "we", "us", "can",
        "could", "would", "should", "have", "has", "had", "get", "got", "show",
        "give", "know", "remember", "working", "work", "continue", "resume",
        "where", "when", "which", "who", "how", "why", "now", "last", "next",
        "from", "into", "over", "again", "still", "just", "any", "all", "some",
    }
)

_WORD_RE = re.compile(r"[A-Za-z0-9_.-]{2,}")
_PATH_RE = re.compile(r"(?:~|\.{1,2})?/[\w./-]+|~[\w./-]*")

# --- weights ---------------------------------------------------------------
# Chosen so that one strong structural signal (an exact key hit, or a path that
# matches the workspace the user is actually in) outranks any amount of weak
# recency. Recency breaks ties; it never wins on its own.
WEIGHT_EXACT_KEY = 10.0
WEIGHT_KEYWORD_IN_KEY = 6.0
WEIGHT_KEYWORD_IN_VALUE = 3.0
WEIGHT_ACTIVE_WORKSPACE_PATH = 8.0
WEIGHT_NAMED_PATH = 9.0
WEIGHT_INTENT_TYPE = 4.0
WEIGHT_RECENT = 2.0
WEIGHT_HIGH_CONFIDENCE = 1.0
PENALTY_STALE = -5.0

#: Below this, a memory is not worth the tokens. A memory whose only claim is
#: "it exists and is recent" scores 3.0 and is correctly excluded.
MIN_SCORE = 4.0

#: Memory types each intent cares about, used for a modest nudge rather than a
#: filter — an unusual but strongly-matching memory should still surface.
INTENT_TYPES: dict[str, frozenset[str]] = {
    "CONTINUE": frozenset({"TASK_CONTEXT", "DECISION", "PROJECT", "WORKSPACE"}),
    "ORIENT": frozenset({"TASK_CONTEXT", "PROJECT", "WORKSPACE"}),
    "WHAT_CHANGED": frozenset({"DECISION", "TASK_CONTEXT"}),
    "RECALL": frozenset(),
    "GENERAL": frozenset(),
}


def keywords(text: str) -> list[str]:
    """The words in a message that could identify a memory."""
    found = [word.casefold() for word in _WORD_RE.findall(text or "")]
    seen: dict[str, None] = {}
    for word in found:
        if word not in STOPWORDS and not word.isdigit():
            seen.setdefault(word, None)
    return list(seen)[:12]


def named_paths(text: str) -> list[str]:
    """Paths the user typed out. Never inferred — see §13."""
    return list(dict.fromkeys(_PATH_RE.findall(text or "")))


def _normalise(path: str) -> str:
    return path.rstrip("/").casefold()


def _value_text(value: Any) -> str:
    if isinstance(value, dict):
        return " ".join(f"{k} {v}" for k, v in value.items()).casefold()
    return str(value).casefold()


@dataclass(frozen=True, slots=True)
class Scored:
    """A memory with its score and the reasons for it."""

    memory: Any
    score: float
    reasons: tuple[str, ...]

    @property
    def relevant(self) -> bool:
        return self.score >= MIN_SCORE


def score_memory(
    memory: Any,
    *,
    words: Sequence[str],
    paths: Sequence[str],
    active_workspace: str | None,
    intent: str,
) -> Scored:
    """Score one memory against the request. ``memory`` is a mapping as
    returned by ``list_memories``."""
    key = str(memory.get("key", "")).casefold()
    mem_type = str(memory.get("type", ""))
    value = memory.get("value")
    value_text = _value_text(value)
    mem_path = value.get("path") if isinstance(value, dict) else None

    score = 0.0
    reasons: list[str] = []

    if key and key in words:
        score += WEIGHT_EXACT_KEY
        reasons.append(f"key '{key}' named in the request")
    else:
        for word in words:
            if word and word in key:
                score += WEIGHT_KEYWORD_IN_KEY
                reasons.append(f"key matches '{word}'")
                break

    for word in words:
        if word and word in value_text:
            score += WEIGHT_KEYWORD_IN_VALUE
            reasons.append(f"value mentions '{word}'")
            break

    if mem_path:
        normalised = _normalise(str(mem_path))
        if any(_normalise(p) == normalised for p in paths):
            score += WEIGHT_NAMED_PATH
            reasons.append("path named in the request")
        elif active_workspace and _normalise(active_workspace).startswith(normalised):
            score += WEIGHT_ACTIVE_WORKSPACE_PATH
            reasons.append("path contains the active workspace")
        elif active_workspace and normalised.startswith(_normalise(active_workspace)):
            score += WEIGHT_ACTIVE_WORKSPACE_PATH
            reasons.append("path is inside the active workspace")

    if mem_type in INTENT_TYPES.get(intent, frozenset()):
        score += WEIGHT_INTENT_TYPE
        reasons.append(f"{mem_type} matters for {intent.lower()}")

    age = memory.get("age_days")
    if isinstance(age, (int, float)) and age <= 7:
        score += WEIGHT_RECENT
        reasons.append("updated in the last week")

    if str(memory.get("confidence_level", "")) == "HIGH":
        score += WEIGHT_HIGH_CONFIDENCE
        reasons.append("high confidence")

    if memory.get("stale"):
        score += PENALTY_STALE
        reasons.append("stale — kept only to be reported as out of date")

    return Scored(memory=memory, score=score, reasons=tuple(reasons))


def rank(
    memories: Iterable[Any],
    *,
    message: str,
    active_workspace: str | None = None,
    intent: str = "GENERAL",
    limit: int = 10,
) -> list[Scored]:
    """The memories worth showing, best first.

    ``RECALL`` is the exception that proves the rule: when the user asks what
    NEXUS remembers, relevance to a topic is not the question, so scoring is
    bypassed and recency decides.
    """
    words = keywords(message)
    paths = named_paths(message)
    scored = [
        score_memory(
            memory,
            words=words,
            paths=paths,
            active_workspace=active_workspace,
            intent=intent,
        )
        for memory in memories
    ]
    if intent == "RECALL":
        return scored[:limit]
    relevant = [item for item in scored if item.relevant]
    relevant.sort(key=lambda item: item.score, reverse=True)
    return relevant[:limit]


def explain(scored: Scored) -> str:
    """Why this memory was included, in the user's language."""
    return "; ".join(scored.reasons) if scored.reasons else "no specific signal"


__all__ = [
    "MIN_SCORE",
    "Scored",
    "explain",
    "keywords",
    "named_paths",
    "rank",
    "score_memory",
]
