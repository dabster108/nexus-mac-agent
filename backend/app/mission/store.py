"""Mission storage.

In-memory for this phase, per spec — no PostgreSQL, no Redis. Kept behind a
small :class:`Protocol` rather than a bare dict scattered through the engine,
so a persistent implementation can be dropped in later without touching
:mod:`app.mission.engine`.
"""

from __future__ import annotations

from collections import OrderedDict
from functools import lru_cache
from typing import Protocol

from app.mission.state import Mission

MAX_MISSIONS = 200


class MissionRepository(Protocol):
    def add(self, mission: Mission) -> None: ...
    def get(self, mission_id: str) -> Mission | None: ...
    def list(self) -> list[Mission]: ...


class InMemoryMissionStore:
    """The default repository: missions live only as long as the process."""

    def __init__(self, max_missions: int = MAX_MISSIONS) -> None:
        self._missions: OrderedDict[str, Mission] = OrderedDict()
        self._max = max_missions

    def add(self, mission: Mission) -> None:
        self._missions[mission.id] = mission
        while len(self._missions) > self._max:
            self._missions.popitem(last=False)

    def get(self, mission_id: str) -> Mission | None:
        return self._missions.get(mission_id)

    def list(self) -> list[Mission]:
        return list(reversed(self._missions.values()))


@lru_cache(maxsize=1)
def get_mission_store() -> InMemoryMissionStore:
    return InMemoryMissionStore()
