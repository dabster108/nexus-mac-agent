"""The timer that drives the sensors.

A single asyncio task, started with the application and cancelled with it. It
does one thing per tick: ask the detector to look. There is no model in this
loop and no work queued from it — §19's distinction, made structural.

The interval is a deliberate compromise. Short enough that a crashed dev server
is noticed while the user still cares, long enough that a laptop is not doing
`git status` continuously. Every sweep is bounded by the detector's own limits.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable

from app.core.logging import get_logger
from app.observations.detector import Detector
from app.tools.registry import ToolRegistry

logger = get_logger(__name__)

DEFAULT_INTERVAL_SECONDS = 10.0

#: Nothing may poll faster than this, whatever it is configured with.
MIN_INTERVAL_SECONDS = 5.0

RegistryFactory = Callable[[], Awaitable[ToolRegistry | None]]


class ObservationScheduler:
    """Runs :meth:`Detector.sweep` on a timer."""

    def __init__(
        self,
        detector: Detector,
        registry_factory: RegistryFactory,
        *,
        interval_seconds: float = DEFAULT_INTERVAL_SECONDS,
    ) -> None:
        self._detector = detector
        self._registry_factory = registry_factory
        self._interval = max(interval_seconds, MIN_INTERVAL_SECONDS)
        self._task: asyncio.Task[None] | None = None

    @property
    def running(self) -> bool:
        return self._task is not None and not self._task.done()

    def start(self) -> None:
        if self.running:
            return
        self._task = asyncio.create_task(self._loop(), name="nexus-observations")
        logger.info("Observation scheduler started (every %.0fs)", self._interval)

    async def stop(self) -> None:
        if self._task is None:
            return
        self._task.cancel()
        try:
            await self._task
        except asyncio.CancelledError:
            pass
        finally:
            self._task = None
            logger.info("Observation scheduler stopped")

    async def tick(self) -> None:
        """One sweep. Separated from the loop so tests never need a timer."""
        registry = await self._registry_factory()
        if registry is None:
            return
        await self._detector.sweep(registry)

    async def _loop(self) -> None:
        while True:
            await asyncio.sleep(self._interval)
            try:
                await self.tick()
            except asyncio.CancelledError:
                raise
            except Exception:  # noqa: BLE001 - the loop outlives any one failure
                logger.warning("Observation sweep failed", exc_info=True)


__all__ = [
    "DEFAULT_INTERVAL_SECONDS",
    "MIN_INTERVAL_SECONDS",
    "ObservationScheduler",
]
