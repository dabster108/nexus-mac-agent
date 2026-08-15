"""Spotting the few statements worth remembering without being asked.

§9 wants this conservative, and the asymmetry is the reason: a missed memory
costs the user one sentence next time, while a wrong one is a false fact that
outlives the conversation and quietly steers later answers. So this only fires
on sentences where the user states a durable fact about their setup in the
present tense, and it never writes anything — it produces a *suggestion* that
still has to go through ``save_memory``, which is CONFIRM, which means the
user sees it before it exists.

What is deliberately not extracted: anything about how something is behaving
right now ("the backend is broken", "the tests are failing"), anything
conditional or future ("we might move to 8123"), and anything the secret
detector would reject — that last one is enforced again downstream regardless.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

#: Present-tense statements of a durable setting. Each pattern names the value
#: it captures; anything not matched here is simply not remembered.
_PATTERNS: tuple[tuple[str, str, re.Pattern[str]], ...] = (
    (
        "DECISION",
        "port",
        re.compile(
            r"\b(?:we(?:'re| are)? |i(?:'m| am)? )?(?:now )?us(?:e|ing) "
            r"port (?P<value>\d{2,5})\b",
            re.I,
        ),
    ),
    (
        "DECISION",
        "port",
        re.compile(
            r"\bthe (?P<what>[\w-]+) (?:now )?runs on port (?P<value>\d{2,5})\b", re.I
        ),
    ),
    (
        "DECISION",
        "port",
        re.compile(
            r"\bport (?P<value>\d{2,5}) for the (?P<what>[\w-]+)\b", re.I
        ),
    ),
)

#: If any of these appear, the sentence is about a moment rather than a fact.
#:
#: "is running" earns its place here: §8's whole example turns on the
#: difference between "the backend *runs* on 8000" (how it is set up) and "the
#: backend *is running* on 8000" (what is true this minute). The second is
#: something to check, not something to remember.
_TRANSIENT = re.compile(
    r"\b(broken|failing|failed|down|crashed|stuck|hanging|slow|weird|"
    r"might|maybe|perhaps|thinking of|planning to|should we|used to|"
    r"was |were |yesterday|earlier|temporarily|for now|just testing|"
    r"is running|are running|is up|is live|currently)\b",
    re.I,
)

#: Phrases that mark a statement as a standing fact rather than a passing one.
#: With one of these present, a wider range of sentences is worth offering to
#: remember; without one, only the narrow patterns above qualify.
_DURABLE = re.compile(
    r"\b(from now on|usually|normally|generally|always|by default|"
    r"i prefer|we prefer|i like|we use|i use|our convention|"
    r"remember that|keep in mind)\b",
    re.I,
)

#: The parts of a project a fact is usually *about*. Used to name the memory
#: after its subject rather than after whichever word happened to precede it.
_SUBJECTS = (
    "backend", "frontend", "api", "server", "database", "db", "worker",
    "client", "app", "service", "proxy", "gateway",
)

#: Statements of preference or convention, allowed only alongside a durable
#: marker. The marker is what makes them a rule rather than a remark.
_DURABLE_PATTERNS: tuple[tuple[str, str, re.Pattern[str]], ...] = (
    (
        "DECISION",
        "port",
        re.compile(r"\bport (?P<value>\d{2,5})\b", re.I),
    ),
    (
        "USER_PREFERENCE",
        "tool",
        re.compile(
            r"\b(?:i|we) (?:prefer|like|use)\s+(?P<value>[\w.+-]{2,30})", re.I
        ),
    ),
)

#: A question is not a statement of fact, however much it looks like one.
_QUESTION = re.compile(r"\?\s*$|^\s*(?:what|which|where|when|why|how|is|are|do|does|did)\b", re.I)


@dataclass(frozen=True, slots=True)
class MemorySuggestion:
    """A fact worth offering to remember. Never itself a memory."""

    type: str
    key: str
    value: dict
    reason: str

    def to_dict(self) -> dict:
        return {
            "type": self.type,
            "key": self.key,
            "value": self.value,
            "reason": self.reason,
        }


def suggest(message: str, *, workspace: str | None = None) -> MemorySuggestion | None:
    """The one durable fact this message states, if it clearly states one.

    Returns at most one suggestion: a message containing several rememberable
    facts is exactly the kind of message this should not be guessing about.
    """
    text = (message or "").strip()
    if not text or _QUESTION.search(text) or _TRANSIENT.search(text):
        return None

    # A durable marker ("from now on", "we always") widens what counts, because
    # the user has said outright that this is how things are rather than how
    # they happen to be right now.
    if _DURABLE.search(text):
        for memory_type, field, pattern in _DURABLE_PATTERNS:
            match = pattern.search(text)
            if not match:
                continue
            value = match.group("value")
            lowered = text.casefold()
            subject = next((s for s in _SUBJECTS if s in lowered), "")
            key = f"{subject}_{field}" if subject else field
            payload: dict = {field: int(value) if value.isdigit() else value}
            if workspace:
                payload["path"] = workspace
            return MemorySuggestion(
                type=memory_type,
                key=key,
                value=payload,
                reason=f"you said this is how you usually work ({field} {value})",
            )

    for memory_type, field, pattern in _PATTERNS:
        match = pattern.search(text)
        if not match:
            continue
        value = match.group("value")
        what = (match.groupdict().get("what") or "").strip().lower()
        key = f"{what}_{field}" if what else field
        payload: dict = {field: int(value) if value.isdigit() else value}
        if workspace:
            payload["path"] = workspace
        return MemorySuggestion(
            type=memory_type,
            key=key,
            value=payload,
            reason=f"you said {field} {value}",
        )
    return None


__all__ = ["MemorySuggestion", "suggest"]
