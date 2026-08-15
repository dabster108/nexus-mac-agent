"""Deciding whether an observation is worth suggesting anything about.

The engine sits between two stores and touches nothing else. It has no tool
registry, no MCP client and no model — by construction, not by convention:
there is nothing in this module's imports that could reach the machine. Its
whole job is to turn "this happened" into "you might want to do this", and
then stop.

It also keeps the small amount of state a good suggestion needs that a single
observation cannot carry — chiefly how many times a process has stopped, which
is the difference between "your backend crashed" and "your backend keeps
crashing".
"""

from __future__ import annotations

from collections import Counter

from app.core.logging import get_logger
from app.observations.models import Category as ObservationCategory
from app.observations.models import Observation
from app.observations.store import ObservationStore
from app.suggestions import rules
from app.suggestions.models import Suggestion
from app.suggestions.store import SuggestionStore

logger = get_logger(__name__)


class SuggestionEngine:
    """Observations in, suggestions out. Nothing else."""

    def __init__(self, suggestions: SuggestionStore) -> None:
        self._suggestions = suggestions
        #: How often each process has been seen to stop. Bounded by the number
        #: of processes NEXUS manages, which the process manager caps at 8.
        self._stops: Counter[str] = Counter()

    def consider(self, observation: Observation) -> Suggestion | None:
        """Offer a suggestion for this observation, if it earns one."""
        repeats = 1
        if (
            observation.category is ObservationCategory.PROCESS
            and observation.actionable
            and observation.related_process_id
        ):
            self._stops[observation.related_process_id] += 1
            repeats = self._stops[observation.related_process_id]

        suggestion = rules.from_observation(observation, repeats=repeats)
        if suggestion is None:
            return None
        return self._suggestions.offer(suggestion)

    def consider_message(
        self, message: str, *, workspace: str | None = None
    ) -> Suggestion | None:
        """Offer to remember something the user just stated as a standing fact."""
        from app.context.extraction import suggest as extract

        try:
            extracted = extract(message, workspace=workspace)
        except Exception:  # noqa: BLE001 - suggesting must not break a request
            logger.warning("Could not read a message for memory", exc_info=True)
            return None
        suggestion = rules.from_memory_statement(extracted, workspace=workspace)
        if suggestion is None:
            return None
        return self._suggestions.offer(suggestion)

    def consider_processes(self, processes: list[dict]) -> list[Suggestion]:
        """Standing conditions, which no single observation describes."""
        offered: list[Suggestion] = []
        for process in processes:
            suggestion = rules.long_running_process(process)
            if suggestion is not None:
                recorded = self._suggestions.offer(suggestion)
                if recorded:
                    offered.append(recorded)
        return offered

    def attach_to(self, observations: ObservationStore) -> None:
        """Listen to the observation store.

        Deliberately a subscriber rather than a call inside the detector: the
        detector's job is to notice, and it should keep working identically
        whether or not anything is listening.
        """

        def sink(observation: Observation, action: str) -> None:
            if action != "created":
                return
            try:
                self.consider(observation)
            except Exception:  # noqa: BLE001 - suggesting must not break observing
                logger.warning("Could not consider an observation", exc_info=True)

        observations.subscribe(sink)


_engine: SuggestionEngine | None = None


def get_suggestion_engine() -> SuggestionEngine:
    from app.suggestions.store import get_suggestion_store

    global _engine
    if _engine is None:
        _engine = SuggestionEngine(get_suggestion_store())
    return _engine


__all__ = ["SuggestionEngine", "get_suggestion_engine"]
