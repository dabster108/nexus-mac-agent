"""Assembling the observation subsystem for the running application.

Kept apart from :mod:`app.main` so the pieces can be built in a test without a
FastAPI lifespan, and apart from the detector so the detector never has to know
where its tools come from.
"""

from __future__ import annotations

from app.agent.tasks import TaskStore, get_task_store
from app.core.logging import get_logger
from app.mcp.registry import MCPSessionPool
from app.observations.detector import Detector, get_detector
from app.observations.publisher import attach
from app.observations.scheduler import ObservationScheduler
from app.observations.store import get_observation_store
from app.tools.registry import ToolRegistry

logger = get_logger(__name__)

#: Watched out of the box, because they are the two things this project runs.
#: Registering a service is otherwise the user's call; nothing is discovered
#: and probed automatically.
DEFAULT_SERVICES: tuple[tuple[str, str], ...] = (
    ("backend", "http://127.0.0.1:8000/health"),
    ("frontend", "http://127.0.0.1:3000"),
)


def build_scheduler(
    pool: MCPSessionPool,
    *,
    detector: Detector | None = None,
    tasks: TaskStore | None = None,
) -> ObservationScheduler:
    """The detector, its delivery path and its timer, wired together."""
    detector = detector or get_detector()
    tasks = tasks or get_task_store()
    attach(get_observation_store(), tasks)

    for name, url in DEFAULT_SERVICES:
        detector.register_service(name, url)

    async def registry_factory() -> ToolRegistry | None:
        # No pool means no tools to read through; the sweep simply does
        # nothing rather than opening its own sessions in the background.
        if not pool.is_open:
            return None
        registry = ToolRegistry(pool.sources)
        await registry.refresh()
        return registry

    return ObservationScheduler(detector, registry_factory)


__all__ = ["DEFAULT_SERVICES", "build_scheduler"]
