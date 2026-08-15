"""The sensors: read current state through SAFE tools, compare, record.

This is not a second agent. There is no model call anywhere in this module and
no way to add one: the detector reads, :mod:`app.observations.rules` decides,
and the store records. The LLM only ever sees an observation if the *user*
asks about it.

The same SAFE-only door as the context collector applies here, enforced the
same way — a detector that could reach a CONFIRM tool would be a background
process that can act on the machine, which is exactly what §11 forbids.
"""

from __future__ import annotations

from typing import Any

from app.core.logging import get_logger
from app.observations import rules
from app.observations.models import Observation
from app.observations.rules import GitState, ServiceState
from app.observations.store import ObservationStore
from app.tools.permissions import PermissionLevel
from app.tools.registry import ToolRegistry

logger = get_logger(__name__)

#: A person can meaningfully register a handful of services. Anything past this
#: is a misconfiguration, and each one costs a request per sweep.
MAX_MONITORED_SERVICES = 8

#: Floor on how often any one service is polled, whatever the caller asks for.
MIN_SERVICE_CHECK_SECONDS = 5.0


class Detector:
    """Holds the previous view of the world and reports what changed."""

    def __init__(self, store: ObservationStore) -> None:
        self._store = store
        self._processes: dict[str, dict[str, Any]] = {}
        self._services: dict[str, ServiceState] = {}
        self._git: dict[str, GitState] = {}
        self._seeded = False

    # --- the SAFE-only door ------------------------------------------------

    async def _call_safe(
        self, registry: ToolRegistry, tool_name: str, arguments: dict
    ) -> dict | None:
        definition = registry.get(tool_name)
        if definition is None:
            return None
        if definition.permission is not PermissionLevel.SAFE:
            # Defensive: a background sensor must never reach a tool that acts.
            logger.error("Detector refused to call non-SAFE tool '%s'", tool_name)
            return None
        try:
            result = await registry.call(tool_name, arguments)
        except Exception:  # noqa: BLE001 - a sensor failure must not stop the loop
            logger.warning("Detector: '%s' failed", tool_name, exc_info=True)
            return None
        if result.is_error or not isinstance(result.structured, dict):
            return None
        return result.structured

    # --- services ----------------------------------------------------------

    def register_service(self, name: str, url: str) -> bool:
        """Watch a local service. Returns False when the ceiling is reached."""
        if name in self._services:
            self._services[name] = ServiceState(name=name, url=url)
            return True
        if len(self._services) >= MAX_MONITORED_SERVICES:
            logger.warning("Refusing to monitor '%s': already at the limit", name)
            return False
        self._services[name] = ServiceState(name=name, url=url)
        return True

    def unregister_service(self, name: str) -> None:
        self._services.pop(name, None)

    @property
    def monitored_services(self) -> list[ServiceState]:
        return list(self._services.values())

    # --- one sweep ---------------------------------------------------------

    async def sweep(self, registry: ToolRegistry) -> list[Observation]:
        """Look once at everything being watched. Never raises."""
        found: list[Observation] = []
        found += await self._sweep_processes(registry)
        found += await self._sweep_services(registry)
        found += await self._sweep_git(registry)
        # The first sweep establishes a baseline rather than announcing the
        # world as it already was — otherwise every restart reports everything.
        self._seeded = True
        return [o for o in found if o is not None]

    async def _sweep_processes(self, registry: ToolRegistry) -> list[Observation]:
        listed = await self._call_safe(registry, "list_processes", {})
        if listed is None:
            return []

        current = {
            str(p.get("process_id")): p
            for p in listed.get("processes", [])
            if p.get("process_id")
        }
        out: list[Observation] = []

        if self._seeded:
            for process_id, process in current.items():
                observation = rules.process_transition(
                    self._processes.get(process_id), process
                )
                if observation:
                    recorded = self._store.record(observation)
                    if recorded:
                        out.append(recorded)

            for process_id, previous in self._processes.items():
                if process_id not in current:
                    observation = rules.process_disappeared(previous)
                    if observation:
                        recorded = self._store.record(observation)
                        if recorded:
                            out.append(recorded)

        self._processes = current
        return out

    async def _sweep_services(self, registry: ToolRegistry) -> list[Observation]:
        if not self._services:
            return []
        out: list[Observation] = []
        for name, service in list(self._services.items()):
            result = await self._call_safe(
                registry, "check_local_service", {"url": service.url}
            )
            if result is None:
                continue
            reachable = bool(result.get("reachable"))
            observation = rules.service_transition(
                service, reachable, detail=result.get("error") or result.get("status_code")
            )
            self._services[name] = ServiceState(
                name=name, url=service.url, status="UP" if reachable else "DOWN"
            )
            if observation:
                recorded = self._store.record(observation)
                if recorded:
                    out.append(recorded)
        return out

    async def _sweep_git(self, registry: ToolRegistry) -> list[Observation]:
        """Watch the workspaces the managed processes are actually in.

        Deliberately not "every workspace ever mentioned": the directories
        NEXUS started something in are the ones the user is demonstrably
        working in, and each extra path costs a `git_status` per sweep.
        """
        paths = {
            p.get("working_directory")
            for p in self._processes.values()
            if p.get("working_directory")
        }
        paths.update(self._git)
        out: list[Observation] = []
        for path in list(paths)[:3]:
            status = await self._call_safe(registry, "git_status", {"path": path})
            if not status or not status.get("success"):
                continue
            changed = status.get("changed_count")
            if changed is None:
                changed = len(status.get("changes") or [])
            current = GitState(
                path=str(path),
                branch=status.get("branch"),
                changed_files=changed,
                head=status.get("head") or status.get("commit"),
            )
            if self._seeded:
                observation = rules.git_transition(self._git.get(path), current)
                if observation:
                    recorded = self._store.record(observation)
                    if recorded:
                        out.append(recorded)
            self._git[str(path)] = current
        return out

    # --- events from elsewhere in the system -------------------------------

    def record(self, observation: Observation | None) -> Observation | None:
        """Used by the task/mission lifecycle, which already knows what happened."""
        return self._store.record(observation) if observation else None


_detector: Detector | None = None


def get_detector() -> Detector:
    from app.observations.store import get_observation_store

    global _detector
    if _detector is None:
        _detector = Detector(get_observation_store())
    return _detector


__all__ = [
    "MAX_MONITORED_SERVICES",
    "MIN_SERVICE_CHECK_SECONDS",
    "Detector",
    "get_detector",
]
