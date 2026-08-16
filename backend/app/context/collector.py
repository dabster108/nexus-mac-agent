"""Assembles context before the agent runs.

Everything this module gathers comes from calling *existing* SAFE tools
directly through the registry — never through the model, and never anything
above SAFE. A CONFIRM tool (``save_memory``, ``delete_memory``) is never
touched here; only the agent, subject to the ordinary approval broker, can
call one of those. That boundary is enforced, not just followed by
convention — see :meth:`ContextCollector._call_safe`.

What gets gathered depends on the request (§12). "What's my battery?" does no
filesystem work at all; "continue where I left off" earns the full picture.
The decision is made by :mod:`app.context.intent`, deterministically, before
any tool runs.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from app.agent import events as ev
from app.agent.events import EventSink
from app.context import relevance
from app.context.intent import ContextPlan, Intent, plan_for
from app.context.models import (
    ContextBudget,
    MachineContext,
    PlanningContext,
    ObservationSnapshot,
    ProcessSnapshot,
    RetrievedMemory,
    TaskSnapshot,
    WorkspaceContext,
)
from app.core.logging import get_logger
from app.tools.permissions import PermissionLevel
from app.tools.registry import ToolRegistry

logger = get_logger(__name__)


def _observe_contradiction(memory: RetrievedMemory, conflict: str, observed: Any) -> None:
    """Surface a contradicted memory in the activity feed as well as the run.

    Same fact the ``memory_conflict`` event already carries, in the form the
    user sees when they were not watching the run that found it. Best-effort
    and lazily imported: context collection must not depend on it.
    """
    try:
        from app.observations import rules
        from app.observations.store import get_observation_store

        stored = memory.value.get("port") if isinstance(memory.value, dict) else memory.value
        get_observation_store().record(
            rules.memory_contradiction(
                memory.id, memory.key, stored, observed, "a managed process"
            )
        )
    except Exception:  # noqa: BLE001 - observation must not affect the request
        logger.warning("Could not record a memory observation", exc_info=True)

#: How many commit subjects to carry for a "what changed?" question. Enough to
#: see the shape of recent work, far short of dumping the log (§5).
MAX_RECENT_COMMITS = 5

#: Workspaces verified per request. Candidates are ranked before slicing, so
#: this bounds work rather than truncating arbitrarily.
MAX_WORKSPACE_CANDIDATES = 3

#: How many memories to read before ranking. Matches the store's own
#: MAX_LIST_LIMIT: read the candidate set once, then score it locally rather
#: than making one round trip per keyword.
MEMORY_READ_LIMIT = 50


class ContextCollector:
    """Gathers memory/workspace/machine context for one request."""

    def __init__(
        self,
        registry: ToolRegistry,
        *,
        max_memories: int,
        max_workspace_facts: int,
        budget: ContextBudget | None = None,
    ) -> None:
        self._registry = registry
        self._max_memories = max_memories
        self._max_workspace_facts = max_workspace_facts
        self._budget = budget

    # --- the SAFE-only door ------------------------------------------------

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
        except Exception:  # noqa: BLE001 - context gathering must not sink a request
            logger.warning("Context collection: '%s' failed", tool_name, exc_info=True)
            return None
        if result.is_error or not isinstance(result.structured, dict):
            return None
        return result.structured

    # --- the entry point ---------------------------------------------------

    async def collect(
        self,
        objective: str,
        task_id: str,
        emit: EventSink,
        *,
        recent_tasks: Sequence[TaskSnapshot] = (),
        plan: ContextPlan | None = None,
    ) -> PlanningContext:
        # A caller that already knows how much context it needs says so; a
        # mission does. Otherwise the intent classifier decides (§12).
        plan = plan or plan_for(objective)

        processes = await self._processes() if plan.processes else []
        memories = (
            await self._retrieve_memories(objective, plan, processes, task_id, emit)
            if plan.memories
            else []
        )
        workspaces = (
            await self._detect_workspaces(objective, memories, processes, plan, task_id, emit)
            if plan.workspace
            else []
        )
        machine = await self._machine_context() if plan.machine else None
        observations = self._recent_observations() if plan.observations else []
        last_outcome = self._last_outcome() if plan.observations else None

        active = next((w for w in workspaces if w.active), None)
        memories = self._rescore(memories, objective, active, plan.intent)
        memories = await self._reconcile(memories, workspaces, processes, task_id, emit)

        budget = self._budget
        max_tasks = budget.max_recent_tasks if budget else 5
        context = PlanningContext(
            objective=objective,
            memories=tuple(memories[: self._max_memories]),
            workspaces=tuple(workspaces[: self._max_workspace_facts]),
            machine=machine,
            truncated=len(memories) > self._max_memories,
            processes=tuple(processes),
            recent_tasks=tuple(recent_tasks[:max_tasks]),
            observations=tuple(observations),
            last_outcome=last_outcome,
            intent=str(plan.intent),
        )
        emit(ev.context_collected(task_id, context.summary()))
        return context

    # --- memory ------------------------------------------------------------

    async def _retrieve_memories(
        self,
        objective: str,
        plan: ContextPlan,
        processes: Sequence[ProcessSnapshot],
        task_id: str,
        emit: EventSink,
    ) -> list[RetrievedMemory]:
        if self._registry.get("list_memories") is None:
            return []

        # One broad read, then rank locally. Searching per keyword made as many
        # round trips as the message had words and still missed anything the
        # LIKE query happened not to match.
        result = await self._call_safe("list_memories", {"limit": MEMORY_READ_LIMIT})
        raw = (result or {}).get("memories", [])
        memories = [self._to_retrieved(item) for item in raw]
        emit(
            ev.memory_retrieved(
                task_id, len(memories), ", ".join(relevance.keywords(objective)) or objective
            )
        )
        return memories

    @staticmethod
    def _to_retrieved(raw: dict, reasons: tuple[str, ...] = ()) -> RetrievedMemory:
        return RetrievedMemory(
            id=raw["id"],
            type=raw["type"],
            key=raw["key"],
            value=raw["value"],
            confidence=raw.get("confidence", 0.5),
            stale=bool(raw.get("stale")),
            confidence_level=raw.get("confidence_level", "MEDIUM"),
            last_verified_at=raw.get("last_verified_at"),
            reasons=reasons,
        )

    def _rescore(
        self,
        memories: Sequence[RetrievedMemory],
        objective: str,
        active: WorkspaceContext | None,
        intent: Intent,
    ) -> list[RetrievedMemory]:
        """Keep only what is relevant, and record why (§7, §11)."""
        as_dicts = [
            {
                "id": m.id, "type": m.type, "key": m.key, "value": m.value,
                "confidence_level": m.confidence_level, "stale": m.stale,
            }
            for m in memories
        ]
        by_id = {m.id: m for m in memories}
        # Ranked without the budget applied: relevance decides what *could*
        # be shown, `collect` decides how much fits. Conflating the two made
        # the truncation flag unreachable, since ranking had already cut.
        ranked = relevance.rank(
            as_dicts,
            message=objective,
            active_workspace=active.path if active else None,
            intent=str(intent),
            limit=MEMORY_READ_LIMIT,
        )
        out: list[RetrievedMemory] = []
        for scored in ranked:
            original = by_id[scored.memory["id"]]
            out.append(
                RetrievedMemory(
                    id=original.id, type=original.type, key=original.key,
                    value=original.value, confidence=original.confidence,
                    stale=original.stale, conflict=original.conflict,
                    confidence_level=original.confidence_level,
                    last_verified_at=original.last_verified_at,
                    reasons=scored.reasons,
                )
            )
        return out

    # --- workspace ---------------------------------------------------------

    async def _detect_workspaces(
        self,
        objective: str,
        memories: Sequence[RetrievedMemory],
        processes: Sequence[ProcessSnapshot],
        plan: ContextPlan,
        task_id: str,
        emit: EventSink,
    ) -> list[WorkspaceContext]:
        if self._registry.get("detect_workspace") is None:
            return []

        candidates = self._workspace_candidates(objective, memories, processes)
        if not candidates:
            return []

        workspaces: list[WorkspaceContext] = []
        for index, path in enumerate(candidates[:MAX_WORKSPACE_CANDIDATES]):
            workspace = await self._verify_workspace(
                path, with_history=plan.git_history
            )
            # The first candidate that actually verifies is the active one:
            # candidates are already in precedence order, and a path that does
            # not exist cannot be where the user is working.
            if workspace.verified and not any(w.active for w in workspaces):
                workspace = replace_active(workspace)
            workspaces.append(workspace)
            emit(ev.workspace_detected(task_id, path, workspace.verified))
        return workspaces

    def _workspace_candidates(
        self,
        objective: str,
        memories: Sequence[RetrievedMemory],
        processes: Sequence[ProcessSnapshot],
    ) -> list[str]:
        """Paths that were actually *observed*, in precedence order.

        §13's rule is the whole point: every candidate here was either typed by
        the user, remembered from something they confirmed, or is the working
        directory of a process NEXUS itself started. Nothing is constructed
        from a project name, which is exactly how the Phase 7 hallucinated
        ``/Users/username/...`` path arose.
        """
        candidates: list[str] = []

        def add(path: str | None) -> None:
            if path and path not in candidates:
                candidates.append(path)

        # 1. The user typed it. Decisive on its own: if they named where they
        #    mean, verifying remembered alternatives as well would only spend
        #    tool calls to add places they did not ask about.
        for path in relevance.named_paths(objective):
            add(path)
        if candidates:
            return candidates

        # 2. A process NEXUS started is running there.
        for process in processes:
            add(process.working_directory)
        # 3. A memory the user approved names it.
        for memory in memories:
            if isinstance(memory.value, dict):
                add(memory.value.get("path"))
        return candidates

    async def _verify_workspace(
        self, path: str, *, with_history: bool = False
    ) -> WorkspaceContext:
        detected = await self._call_safe("detect_workspace", {"path": path})
        if not detected or not detected.get("success"):
            return WorkspaceContext(path=path, verified=False)

        git_branch = None
        git_clean = None
        changed_files = None
        commits: tuple[str, ...] = ()

        # Always ask Git, rather than trusting `detect_workspace`'s flag. That
        # flag means "this directory is a repository root"; a subdirectory of
        # one reports false while `git_status` answers for it perfectly well.
        # Skipping the call there left the context silent about the branch, and
        # a model handed silence invents a plausible "main, clean" instead.
        status = await self._call_safe("git_status", {"path": path})
        in_git = bool(status and status.get("success"))
        if in_git:
            git_branch = status.get("branch")
            git_clean = status.get("clean")
            changed_files = status.get("changed_count")
            if changed_files is None:
                changed_files = len(status.get("changes") or []) or None
            if with_history:
                commits = await self._recent_commits(path)

        return WorkspaceContext(
            path=detected.get("path", path),
            verified=True,
            project_types=tuple(detected.get("project_types") or ()),
            is_git_repository=in_git or bool(detected.get("is_git_repository")),
            git_branch=git_branch,
            git_clean=git_clean,
            changed_files=changed_files,
            recent_commits=commits,
        )

    async def _recent_commits(self, path: str) -> tuple[str, ...]:
        log = await self._call_safe("git_log", {"path": path, "limit": MAX_RECENT_COMMITS})
        if not log or not log.get("success"):
            return ()
        subjects = []
        for commit in (log.get("commits") or [])[:MAX_RECENT_COMMITS]:
            subject = commit.get("subject") or commit.get("message") or ""
            if subject:
                subjects.append(subject.splitlines()[0][:80])
        return tuple(subjects)

    # --- processes ---------------------------------------------------------

    async def _processes(self) -> list[ProcessSnapshot]:
        listed = await self._call_safe("list_processes", {})
        out: list[ProcessSnapshot] = []
        for process in (listed or {}).get("processes", []):
            out.append(
                ProcessSnapshot(
                    process_id=process.get("process_id", ""),
                    name=process.get("name") or process.get("command", "process"),
                    status=process.get("status", "UNKNOWN"),
                    port=process.get("port"),
                    working_directory=process.get("working_directory"),
                )
            )
        return out

    # --- reconciliation ----------------------------------------------------

    async def _reconcile(
        self,
        memories: Sequence[RetrievedMemory],
        workspaces: Sequence[WorkspaceContext],
        processes: Sequence[ProcessSnapshot],
        task_id: str,
        emit: EventSink,
    ) -> list[RetrievedMemory]:
        """Compare each memory with what was just observed (§4, §18).

        A disagreement is recorded on the memory *and* written back through
        ``verify_memory`` so the next session starts from the corrected view.
        Nothing is deleted and no value is rewritten — the user owns both of
        those, through ``delete_memory`` and ``save_memory``.
        """
        # A managed process with a port is evidence regardless of the status
        # string: NEXUS started it there, which is what makes it live evidence.
        live_ports = {
            p.working_directory: p.port
            for p in processes
            if p.working_directory and p.port
        }
        verified_paths = {w.path for w in workspaces if w.verified}
        missing_paths = {w.path for w in workspaces if not w.verified}

        out: list[RetrievedMemory] = []
        for memory in memories:
            conflict = None
            value = memory.value if isinstance(memory.value, dict) else {}
            path = value.get("path")
            remembered_port = value.get("port")

            if path and path in live_ports and remembered_port is not None:
                if remembered_port != live_ports[path]:
                    conflict = (
                        f"remembered port {remembered_port}, but the process running "
                        f"there is on port {live_ports[path]}"
                    )
            elif path and path in missing_paths:
                conflict = "the remembered path no longer exists"

            if conflict:
                emit(ev.memory_conflict(task_id, memory.key, conflict))
                _observe_contradiction(memory, conflict, live_ports.get(path))
                await self._call_safe(
                    "verify_memory", {"memory_id": memory.id, "outcome": "stale"}
                )
                out.append(
                    RetrievedMemory(
                        id=memory.id, type=memory.type, key=memory.key,
                        value=memory.value, confidence=memory.confidence,
                        stale=True, conflict=conflict,
                        confidence_level=memory.confidence_level,
                        last_verified_at=memory.last_verified_at,
                        reasons=memory.reasons,
                    )
                )
                continue

            if path and path in verified_paths and not memory.stale:
                await self._call_safe(
                    "verify_memory", {"memory_id": memory.id, "outcome": "confirmed"}
                )
            out.append(memory)
        return out

    # --- observations ------------------------------------------------------

    def _recent_observations(self) -> list[ObservationSnapshot]:
        """What NEXUS has already noticed, for "what happened recently?".

        Read straight from the store rather than re-inspecting the machine: the
        question is about the past, and the observations *are* the evidence.
        Their text was sanitised when they were created, so nothing further is
        done to it here.
        """
        budget = self._budget
        limit = budget.max_observations if budget else 10
        try:
            from app.observations.store import get_observation_store

            found = get_observation_store().list(limit=limit)
        except Exception:  # noqa: BLE001 - context must not depend on the feed
            logger.warning("Could not read observations for context", exc_info=True)
            return []
        # Oldest first, so the prompt reads as a sequence of events.
        return [
            ObservationSnapshot(
                observation_id=item.observation_id,
                category=str(item.category),
                severity=str(item.severity),
                line=item.to_line(),
            )
            for item in reversed(found)
        ]

    @staticmethod
    def _last_outcome() -> str | None:
        """What the last action was verified to have achieved.

        Bounded to its own prompt block, which is already the sanitised,
        evidence-only rendering — no new text is composed here.
        """
        try:
            from app.verification.outcomes import last_outcome

            found = last_outcome()
        except Exception:  # noqa: BLE001 - context must not depend on it
            return None
        if found is None:
            return None
        verification, request = found
        return f"Request: {request}\n{verification.to_prompt_block()}"

    # --- machine -----------------------------------------------------------

    async def _machine_context(self) -> MachineContext | None:
        info = await self._call_safe("system_info", {})
        if not info or not info.get("success"):
            return None
        battery = await self._call_safe("battery_status", {})
        has_battery = bool(battery and battery.get("success"))
        return MachineContext(
            platform=info.get("platform", "unknown"),
            architecture=info.get("architecture", "unknown"),
            cpu_count=info.get("cpu_count", 0) or 0,
            battery_percentage=battery.get("percentage") if has_battery else None,
            charging=battery.get("charging") if has_battery else None,
        )


def replace_active(workspace: WorkspaceContext) -> WorkspaceContext:
    """A copy of ``workspace`` marked as the active one."""
    return WorkspaceContext(
        path=workspace.path,
        verified=workspace.verified,
        project_types=workspace.project_types,
        is_git_repository=workspace.is_git_repository,
        git_branch=workspace.git_branch,
        git_clean=workspace.git_clean,
        changed_files=workspace.changed_files,
        recent_commits=workspace.recent_commits,
        active=True,
    )
