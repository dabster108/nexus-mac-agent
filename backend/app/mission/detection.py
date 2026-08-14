"""Deciding whether a chat message is a mission or an ordinary request.

This is a deliberately simple, deterministic heuristic — not an LLM call. Two
things follow from that choice, both intentional:

* Every message that does *not* look like a mission takes the exact code path
  it always has (:meth:`AgentRunner._execute`), with zero added latency and
  zero behaviour change. A single factual question should not pay for a
  planning round trip it doesn't need.
* The heuristic can be wrong in both directions. A future phase could replace
  it with a fast classifier call, or let the client opt in explicitly; for now
  it is intentionally conservative and its accuracy is a known, documented
  limitation rather than something masked by an LLM call for every message.
"""

from __future__ import annotations

import re

#: Phrases that name a mission outright, or a multi-step objective by nature.
_TRIGGER_PATTERNS: tuple[re.Pattern[str], ...] = tuple(
    re.compile(pattern)
    for pattern in (
        r"\bprepare\b",
        r"\bset ?up\b",
        r"\bdevelopment environment\b",
        r"\bmission\b",
        # "why ... isn't/doesn't/not ... working/responding/up/..." — the two
        # halves are matched separately since real phrasing puts a subject
        # between them ("why isn't my backend responding").
        r"\bwhy\b.{0,60}\b(isn'?t|doesn'?t|is not|not)\b.{0,30}\b"
        r"(work\w*|respond\w*|reachable|running|up)\b",
        r"\bwhy\b.{0,40}\b(broken|down|failing)\b",
    )
)

#: Verbs that name a discrete action. Two or more clauses starting with one of
#: these, joined by "and"/"then"/a comma, reads as an ordered multi-step ask.
_ACTION_VERBS = frozenset(
    {
        "start", "stop", "restart", "check", "run", "inspect", "read", "list",
        "detect", "test", "build", "open", "verify", "find", "show", "diagnose",
    }
)
_CLAUSE_SPLIT = re.compile(r"\band\b|\bthen\b|,")
_LEADING_WORD = re.compile(r"^[a-z']+")


def _clause_action_count(text: str) -> int:
    count = 0
    for clause in _CLAUSE_SPLIT.split(text):
        match = _LEADING_WORD.match(clause.strip())
        if match and match.group(0) in _ACTION_VERBS:
            count += 1
    return count


def looks_like_mission(message: str) -> bool:
    """Whether this message reads as a multi-step objective."""
    text = message.strip().lower()
    if not text:
        return False
    if any(pattern.search(text) for pattern in _TRIGGER_PATTERNS):
        return True
    return _clause_action_count(text) >= 2
