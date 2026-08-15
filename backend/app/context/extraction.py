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
_TRANSIENT = re.compile(
    r"\b(broken|failing|failed|down|crashed|stuck|hanging|slow|weird|"
    r"might|maybe|perhaps|thinking of|planning to|should we|used to|"
    r"was |were |yesterday|earlier|temporarily|for now|just testing)\b",
    re.I,
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
