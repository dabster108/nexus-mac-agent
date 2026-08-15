"""Putting observations onto the stream the client is already watching.

An observation is not a task event — nothing requested it — so it carries a
synthetic task id rather than pretending to belong to a run. Everything else
about it is an ordinary payload on the ordinary socket: one connection, one
event vocabulary, no second streaming system.
"""

from __future__ import annotations

from app.agent.events import EventType
from app.agent.tasks import TaskStore
from app.observations.models import Observation
from app.observations.store import ObservationStore

#: Marks an event that belongs to no run. Clients filtering by their own task
#: id will not match it, which is the intended behaviour: observations are for
#: the session, not for a request.
SYSTEM_TASK_ID = "system"


def observation_payload(observation: Observation, action: str) -> dict:
    event_type = (
        EventType.OBSERVATION_CREATED
        if action == "created"
        else EventType.OBSERVATION_DISMISSED
    )
    return {
        "type": str(event_type),
        "task_id": SYSTEM_TASK_ID,
        "timestamp": observation.created_at,
        "observation": observation.to_public_dict(),
    }


def attach(store: ObservationStore, tasks: TaskStore) -> None:
    """Deliver every observation to the WebSocket subscribers."""

    def sink(observation: Observation, action: str) -> None:
        tasks.broadcast(observation_payload(observation, action))

    store.subscribe(sink)


__all__ = ["SYSTEM_TASK_ID", "attach", "observation_payload"]
