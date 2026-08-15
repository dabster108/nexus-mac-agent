"""Where suggestions live, and everything that stops them nagging.

The failure mode this guards against is not a crash — it is annoyance, which
is why there are four limits rather than one:

* **key collapse** — one condition is one suggestion, however many
  observations describe it. A crash does not produce "backend crashed",
  "process failed" and "backend unavailable" side by side.
* **cooldown** — a dismissed suggestion stays gone for a while, so dismissing
  it means something.
* **pending ceiling** — a person will act on a handful; past that, more
  suggestions make the useful ones harder to see.
* **ring bound** — total storage, as everywhere else.

Expiry is computed on read rather than swept by a timer: a suggestion that
nobody looked at never needed cleaning up.
"""

from __future__ import annotations

import time
from collections import OrderedDict
from collections.abc import Callable
from datetime import UTC, datetime

from app.core.logging import get_logger
from app.suggestions.models import MAX_PENDING, MAX_SUGGESTIONS, Status, Suggestion

logger = get_logger(__name__)

#: How long a dismissed condition stays quiet before it may be raised again.
DISMISSED_COOLDOWN_SECONDS = 1800.0

#: Ceiling per minute, independent of the other limits.
MAX_PER_MINUTE = 10

SuggestionSink = Callable[[Suggestion, str], None]
"""Called as ``(suggestion, action)`` — created / dismissed / expired."""


class SuggestionStore:
    """A bounded set of things NEXUS thinks might be worth doing."""

    def __init__(
        self,
        *,
        max_suggestions: int = MAX_SUGGESTIONS,
        max_pending: int = MAX_PENDING,
        cooldown_seconds: float = DISMISSED_COOLDOWN_SECONDS,
        max_per_minute: int = MAX_PER_MINUTE,
        clock: Callable[[], float] = time.monotonic,
        now: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self._items: OrderedDict[str, Suggestion] = OrderedDict()
        self._max = max_suggestions
        self._max_pending = max_pending
        self._cooldown = cooldown_seconds
        self._max_per_minute = max_per_minute
        self._clock = clock
        self._now = now
        self._dismissed_at: dict[str, float] = {}
        self._recent: list[float] = []
        self._sinks: list[SuggestionSink] = []

    # --- delivery ----------------------------------------------------------

    def subscribe(self, sink: SuggestionSink) -> None:
        self._sinks.append(sink)

    def _publish(self, suggestion: Suggestion, action: str) -> None:
        for sink in list(self._sinks):
            try:
                sink(suggestion, action)
            except Exception:  # noqa: BLE001 - a bad listener must not stop the engine
                logger.warning("A suggestion sink failed", exc_info=True)

    # --- writing -----------------------------------------------------------

    def offer(self, suggestion: Suggestion) -> Suggestion | None:
        """Record a suggestion, or return None if it should stay quiet."""
        self._expire_due()
        now = self._clock()

        if not self._within_rate_limit(now):
            logger.warning("Suggestion rate limit reached; dropping '%s'", suggestion.title)
            return None

        dismissed_at = self._dismissed_at.get(suggestion.key)
        if dismissed_at is not None and now - dismissed_at < self._cooldown:
            # They said no recently. Asking again is how this becomes noise.
            return None

        existing = self._pending_for_key(suggestion.key)
        if existing is not None:
            # One condition, one suggestion — however it was phrased.
            return None

        if len(self.pending()) >= self._max_pending:
            logger.info("Suggestion ceiling reached; dropping '%s'", suggestion.title)
            return None

        self._recent.append(now)
        self._items[suggestion.suggestion_id] = suggestion
        while len(self._items) > self._max:
            self._items.popitem(last=False)

        logger.info("Suggestion [%s] %s", suggestion.category, suggestion.title)
        self._publish(suggestion, "created")
        return suggestion

    def _within_rate_limit(self, now: float) -> bool:
        self._recent = [at for at in self._recent if now - at <= 60.0]
        return len(self._recent) < self._max_per_minute

    def _pending_for_key(self, key: str) -> Suggestion | None:
        for suggestion in reversed(self._items.values()):
            if suggestion.key == key and suggestion.is_pending:
                return suggestion
        return None

    def dismiss(self, suggestion_id: str) -> Suggestion | None:
        return self._resolve(suggestion_id, Status.DISMISSED, "dismissed")

    def accept(self, suggestion_id: str) -> Suggestion | None:
        """Mark it taken up. Accepting performs nothing — the frontend sends
        the ordinary chat message, and this only records that it did."""
        return self._resolve(suggestion_id, Status.ACCEPTED, "dismissed")

    def _resolve(self, suggestion_id: str, status: Status, action: str) -> Suggestion | None:
        existing = self._items.get(suggestion_id)
        if existing is None or not existing.is_pending:
            return None
        updated = existing.with_status(status)
        self._items[suggestion_id] = updated
        if status is Status.DISMISSED:
            self._dismissed_at[existing.key] = self._clock()
        self._publish(updated, action)
        return updated

    def _expire_due(self) -> None:
        now = self._now()
        for suggestion_id, suggestion in list(self._items.items()):
            if suggestion.is_pending and suggestion.has_expired(now):
                expired = suggestion.with_status(Status.EXPIRED)
                self._items[suggestion_id] = expired
                self._publish(expired, "expired")

    # --- reading -----------------------------------------------------------

    def get(self, suggestion_id: str) -> Suggestion | None:
        self._expire_due()
        return self._items.get(suggestion_id)

    def pending(self) -> list[Suggestion]:
        """Newest first."""
        return [s for s in reversed(self._items.values()) if s.is_pending]

    def list(self, *, include_resolved: bool = False, limit: int | None = None) -> list[Suggestion]:
        self._expire_due()
        found = [
            s for s in reversed(self._items.values()) if include_resolved or s.is_pending
        ]
        return found[:limit] if limit else found

    def clear(self) -> None:
        self._items.clear()
        self._dismissed_at.clear()
        self._recent.clear()


_store: SuggestionStore | None = None


def get_suggestion_store() -> SuggestionStore:
    global _store
    if _store is None:
        _store = SuggestionStore()
    return _store


__all__ = [
    "DISMISSED_COOLDOWN_SECONDS",
    "MAX_PER_MINUTE",
    "SuggestionSink",
    "SuggestionStore",
    "get_suggestion_store",
]
