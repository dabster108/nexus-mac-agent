"""Where observations live, and what stops them multiplying.

Three separate limits, because they fail in different ways:

* **dedupe** — the same condition seen twice updates the existing observation
  rather than adding one. A service that is down stays one line.
* **cooldown** — a condition that resolves and recurs within the window does
  not re-announce itself. This is what makes a flapping service quiet.
* **rate limit** — a hard ceiling per minute, independent of the other two, so
  a detector bug cannot fill the ring however novel each observation looks.

The store is deliberately in-memory: observations describe the current session
and are worthless after a restart, unlike memories, which are the thing that
survives one.
"""

from __future__ import annotations

import time
from collections import OrderedDict, deque
from collections.abc import Callable, Iterable

from app.core.logging import get_logger
from app.observations.models import MAX_OBSERVATIONS, Observation

logger = get_logger(__name__)

#: How long the same condition stays quiet after being reported.
DEFAULT_COOLDOWN_SECONDS = 60.0

#: Hard ceiling, whatever the dedupe key says. A broken sensor firing novel
#: observations in a loop is exactly the case the other two limits miss.
MAX_EVENTS_PER_MINUTE = 30

ObservationSink = Callable[[Observation, str], None]
"""Called as ``(observation, action)`` where action is created/dismissed."""


class ObservationStore:
    """A bounded, newest-wins ring of what NEXUS has noticed."""

    def __init__(
        self,
        *,
        max_observations: int = MAX_OBSERVATIONS,
        cooldown_seconds: float = DEFAULT_COOLDOWN_SECONDS,
        max_per_minute: int = MAX_EVENTS_PER_MINUTE,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._observations: OrderedDict[str, Observation] = OrderedDict()
        self._max = max_observations
        self._cooldown = cooldown_seconds
        self._max_per_minute = max_per_minute
        self._clock = clock
        self._last_seen: dict[str, float] = {}
        self._recent: deque[float] = deque()
        self._sinks: list[ObservationSink] = []

    # --- delivery ----------------------------------------------------------

    def subscribe(self, sink: ObservationSink) -> None:
        """Register a delivery callback (the WebSocket broadcast)."""
        self._sinks.append(sink)

    def _publish(self, observation: Observation, action: str) -> None:
        for sink in list(self._sinks):
            try:
                sink(observation, action)
            except Exception:  # noqa: BLE001 - a bad listener must not stop detection
                logger.warning("An observation sink failed", exc_info=True)

    # --- writing -----------------------------------------------------------

    def record(self, observation: Observation) -> Observation | None:
        """Store and announce an observation, or return None if suppressed."""
        now = self._clock()
        if not self._within_rate_limit(now):
            logger.warning(
                "Observation rate limit reached; dropping '%s'", observation.title
            )
            return None

        previous_at = self._last_seen.get(observation.dedupe_key)
        if previous_at is not None and now - previous_at < self._cooldown:
            # Same condition, still inside the window: refresh what is already
            # on screen rather than announcing it again.
            existing = self._find_by_dedupe(observation.dedupe_key)
            if existing is not None:
                return None

        self._last_seen[observation.dedupe_key] = now
        self._recent.append(now)
        self._observations[observation.observation_id] = observation
        while len(self._observations) > self._max:
            self._observations.popitem(last=False)

        logger.info(
            "Observation [%s/%s] %s",
            observation.category, observation.severity, observation.title,
        )
        self._publish(observation, "created")
        return observation

    def _within_rate_limit(self, now: float) -> bool:
        while self._recent and now - self._recent[0] > 60.0:
            self._recent.popleft()
        return len(self._recent) < self._max_per_minute

    def _find_by_dedupe(self, key: str) -> Observation | None:
        for observation in reversed(self._observations.values()):
            if observation.dedupe_key == key and not observation.dismissed:
                return observation
        return None

    def dismiss(self, observation_id: str) -> Observation | None:
        """Mark one as handled. Kept in the ring, so the record stays honest."""
        existing = self._observations.get(observation_id)
        if existing is None or existing.dismissed:
            return None
        updated = Observation(
            **{
                **{
                    slot: getattr(existing, slot)
                    for slot in existing.__slots__
                    if slot != "dismissed"
                },
                "dismissed": True,
            }
        )
        self._observations[observation_id] = updated
        self._publish(updated, "dismissed")
        return updated

    # --- reading -----------------------------------------------------------

    def get(self, observation_id: str) -> Observation | None:
        return self._observations.get(observation_id)

    def list(
        self, *, limit: int | None = None, include_dismissed: bool = False
    ) -> list[Observation]:
        """Newest first."""
        items: Iterable[Observation] = reversed(self._observations.values())
        found = [o for o in items if include_dismissed or not o.dismissed]
        return found[:limit] if limit else found

    def clear(self) -> None:
        """Used by tests and by a fresh session; never by the detector."""
        self._observations.clear()
        self._last_seen.clear()
        self._recent.clear()


_store: ObservationStore | None = None


def get_observation_store() -> ObservationStore:
    """The process-wide store, created on first use."""
    global _store
    if _store is None:
        _store = ObservationStore()
    return _store


__all__ = [
    "DEFAULT_COOLDOWN_SECONDS",
    "MAX_EVENTS_PER_MINUTE",
    "ObservationSink",
    "ObservationStore",
    "get_observation_store",
]
