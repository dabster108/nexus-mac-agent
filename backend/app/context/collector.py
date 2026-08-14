"""Assembles context before planning.

Everything this module gathers comes from calling *existing* SAFE tools
directly through the registry — never through the model, and never anything
above SAFE. A CONFIRM tool (``save_memory``, ``delete_memory``) is never
touched here; only the agent, subject to the ordinary approval broker, can
call one of those. That boundary is enforced, not just followed by
convention — see :func:`ContextCollector._call_safe`.

Machine and workspace facts are gathered fresh, once, right before planning —
never polled continuously (§13).
"""

from __future__ import annotations

import re
from collections.abc import Sequence

from app.agent import events as ev
from app.agent.events import EventSink
from app.context.models import (
    MachineContext,
    PlanningContext,
    RetrievedMemory,
    WorkspaceContext,
)
from app.core.logging import get_logger
from app.tools.permissions import PermissionLevel
from app.tools.registry import ToolRegistry

logger = get_logger(__name__)

#: Common words dropped before turning an objective into search keywords.
_STOPWORDS = frozenset(
    {
        "the", "a", "an", "my", "me", "and", "or", "to", "of", "for", "in",
        "on", "at", "is", "it", "this", "that", "what", "whether", "tell",
        "check", "start", "stop", "run", "please", "then", "with", "about",
        "project", "backend", "frontend",
    }
)
_WORD_RE = re.compile(r"[A-Za-z0-9_./~-]{3,}")
#: A path the user named directly always takes precedence over a remembered one.
_PATH_RE = re.compile(r"(?:~|\.{1,2})?/[\w./-]+|~[\w./-]*")


def _keywords(objective: str) -> list[str]:
    words = [w.casefold() for w in _WORD_RE.findall(objective)]
    return [w for w in words if w not in _STOPWORDS][:8]


def _named_paths(objective: str) -> list[str]:
    return _PATH_RE.findall(objective)


class ContextCollector:
    """Gathers memory/workspace/machine context for one mission objective."""

    def __init__(
        self,
        registry: ToolRegistry,
        *,
        max_memories: int,
        max_workspace_facts: int,
    ) -> None:
        self._registry = registry
        self._max_memories = max_memories
        self._max_workspace_facts = max_workspace_facts

    async def _call_safe(self, tool_name: str, arguments: dict) -> dict | None:
        """Call a tool directly, bypassing the model — only ever for SAFE tools."""
        definition = self._registry.get(tool_name)
        if definition is None:
            return None
        if definition.permission is not PermissionLevel.SAFE:
            # Defensive: context collection must never reach a CONFIRM tool.
            logger.error(
                "Context collector refused to call non-SAFE tool '%s'", tool_name
            )
            return None
        try:
            result = await self._registry.call(tool_name, arguments)
        except Exception:  # noqa: BLE001 - context gathering must not sink a mission
            logger.warning("Context collection: '%s' failed", tool_name, exc_info=True)
            return None
        if result.is_error or not isinstance(result.structured, dict):
            return None
        return result.structured

    async def collect(self, objective: str, task_id: str, emit: EventSink) -> PlanningContext:
        memories = await self._retrieve_memories(objective, task_id, emit)
        workspaces = await self._detect_workspaces(objective, memories, task_id, emit)
        machine = await self._machine_context()

        truncated = len(memories) >= self._max_memories
        context = PlanningContext(
            objective=objective,
            memories=tuple(memories[: self._max_memories]),
            workspaces=tuple(workspaces[: self._max_workspace_facts]),
            machine=machine,
            truncated=truncated,
        )
        emit(ev.context_collected(task_id, context.summary()))
        return context

    async def _retrieve_memories(
        self, objective: str, task_id: str, emit: EventSink
    ) -> list[RetrievedMemory]:
        if self._registry.get("list_memories") is None:
            return []
        keywords = _keywords(objective)
        seen: dict[str, RetrievedMemory] = {}
        for keyword in keywords[:4] or [""]:
            result = await self._call_safe("list_memories", {"query": keyword or None, "limit": self._max_memories})
            for raw in (result or {}).get("memories", []):
                seen[raw["id"]] = RetrievedMemory(
                    id=raw["id"], type=raw["type"], key=raw["key"], value=raw["value"],
                    confidence=raw["confidence"], stale=raw.get("stale", False),
                )
            if len(seen) >= self._max_memories:
                break

        memories = list(seen.values())[: self._max_memories]
        emit(ev.memory_retrieved(task_id, len(memories), ", ".join(keywords) or objective))
        return memories

    async def _detect_workspaces(
        self,
        objective: str,
        memories: Sequence[RetrievedMemory],
        task_id: str,
        emit: EventSink,
    ) -> list[WorkspaceContext]:
        if self._registry.get("detect_workspace") is None:
            return []

        # A path the user named directly always wins over a remembered one.
        candidates = list(dict.fromkeys(_named_paths(objective)))
        if not candidates:
            for memory in memories:
                path = memory.value.get("path") if isinstance(memory.value, dict) else None
                if path and path not in candidates:
                    candidates.append(path)
        if not candidates:
            return []

        live_processes = await self._call_safe("list_processes", {})

        workspaces: list[WorkspaceContext] = []
        for path in candidates[:3]:
            workspace = await self._verify_workspace(path)
            workspaces.append(workspace)
            emit(ev.workspace_detected(task_id, path, workspace.verified))
            self._flag_conflicts(memories, workspace, live_processes, task_id, emit)
        return workspaces

    async def _verify_workspace(self, path: str) -> WorkspaceContext:
        detected = await self._call_safe("detect_workspace", {"path": path})
        if not detected or not detected.get("success"):
            return WorkspaceContext(path=path, verified=False)

        git_branch = None
        git_clean = None
        if detected.get("is_git_repository"):
            status = await self._call_safe("git_status", {"path": path})
            if status and status.get("success"):
                git_branch = status.get("branch")
                git_clean = status.get("clean")

        return WorkspaceContext(
            path=detected.get("path", path),
            verified=True,
            project_types=tuple(detected.get("project_types") or ()),
            is_git_repository=bool(detected.get("is_git_repository")),
            git_branch=git_branch,
            git_clean=git_clean,
        )

    def _flag_conflicts(
        self,
        memories: Sequence[RetrievedMemory],
        workspace: WorkspaceContext,
        live_processes: dict | None,
        task_id: str,
        emit: EventSink,
    ) -> None:
        """§20's exact example, made concrete: a remembered port for this
        workspace that disagrees with what a *currently managed* process
        reports. Only fires on an actual disagreement — a memory with nothing
        live to contradict it is not a conflict, just untested.
        """
        live_port = None
        for process in (live_processes or {}).get("processes", []):
            if process.get("working_directory") == workspace.path and process.get("port"):
                live_port = process["port"]
                break
        if live_port is None:
            return

        for memory in memories:
            if memory.type != "WORKSPACE" or not isinstance(memory.value, dict):
                continue
            remembered_port = memory.value.get("port")
            if memory.value.get("path") != workspace.path or remembered_port is None:
                continue
            if remembered_port == live_port:
                continue
            emit(
                ev.memory_conflict(
                    task_id, memory.key,
                    f"memory says port {remembered_port} for {workspace.path}, but a "
                    f"managed process is currently running on port {live_port}",
                )
            )

    async def _machine_context(self) -> MachineContext | None:
        info = await self._call_safe("system_info", {})
        if not info or not info.get("success"):
            return None
        battery = await self._call_safe("battery_status", {})
        return MachineContext(
            platform=info.get("platform", "unknown"),
            architecture=info.get("architecture", "unknown"),
            cpu_count=info.get("cpu_count", 0) or 0,
            battery_percentage=(battery or {}).get("percentage") if battery and battery.get("success") else None,
            charging=(battery or {}).get("charging") if battery and battery.get("success") else None,
        )
