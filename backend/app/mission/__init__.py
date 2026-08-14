"""The mission engine: multi-step objectives, orchestrated over the existing
single-task agent runtime rather than a second security or execution system.
"""

from app.mission.detection import looks_like_mission
from app.mission.engine import MissionEngine, MissionLimits
from app.mission.planner import MissionPlanningError, create_plan
from app.mission.state import Mission, MissionStatus, MissionStep, StepStatus
from app.mission.store import InMemoryMissionStore, get_mission_store

__all__ = [
    "InMemoryMissionStore",
    "Mission",
    "MissionEngine",
    "MissionLimits",
    "MissionPlanningError",
    "MissionStatus",
    "MissionStep",
    "StepStatus",
    "create_plan",
    "get_mission_store",
    "looks_like_mission",
]
