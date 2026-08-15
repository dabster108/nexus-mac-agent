"""Suggestions onto the WebSocket the client already watches.

Same mechanism Phase 11 used for observations: the existing
:meth:`TaskStore.broadcast`, the existing socket, a synthetic task id because
a suggestion belongs to the session rather than to any run.
"""

from __future__ import annotations

from app.agent.events import EventType
from app.agent.tasks import TaskStore
from app.observations.publisher import SYSTEM_TASK_ID
from app.suggestions.models import Suggestion
from app.suggestions.store import SuggestionStore

_EVENTS = {
    "created": EventType.SUGGESTION_CREATED,
    "dismissed": EventType.SUGGESTION_DISMISSED,
    "expired": EventType.SUGGESTION_EXPIRED,
}


def suggestion_payload(suggestion: Suggestion, action: str) -> dict:
    return {
        "type": str(_EVENTS.get(action, EventType.SUGGESTION_CREATED)),
        "task_id": SYSTEM_TASK_ID,
        "timestamp": suggestion.created_at,
        "suggestion": suggestion.to_public_dict(),
    }


def attach(store: SuggestionStore, tasks: TaskStore) -> None:
    def sink(suggestion: Suggestion, action: str) -> None:
        tasks.broadcast(suggestion_payload(suggestion, action))

    store.subscribe(sink)


__all__ = ["attach", "suggestion_payload"]
