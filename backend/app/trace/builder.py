"""Projecting a finished (or running) task into a trace.

Everything comes from :class:`~app.agent.tasks.TaskRecord.events` — the same
stream the frontend already watches — plus the context packet the runner kept
for that task. Nothing is re-collected, no tool is called, and no model is
asked what happened. That is what makes the trace an audit rather than a
retelling: if an event did not fire, it does not appear.

Building a trace is best-effort by contract. A failure here must never change
what a task reports, so every caller treats an exception as "no trace".
"""

from __future__ import annotations

from typing import Any

from app.agent.events import EventType
from app.core.logging import get_logger
from app.observations.models import clean
from app.trace import explain
from app.trace.models import (
    MAX_EVIDENCE_PER_TRACE,
    MAX_TRACE_CHARS,
    MAX_TRACE_ITEMS,
    ContextItem,
    EvidenceItem,
    Mark,
    Phase,
    Trace,
    TraceStep,
)

logger = get_logger(__name__)

#: Events that become a step. Anything not listed is deliberately not shown —
#: a trace that mirrors every event is the event log again, not an explanation.
_STEP_EVENTS = {
    EventType.TOOL_REQUESTED,
    EventType.PERMISSION_REQUIRED,
    EventType.TOOL_STARTED,
    EventType.TOOL_COMPLETED,
    EventType.VERIFICATION_STARTED,
    EventType.VERIFICATION_COMPLETED,
    EventType.TASK_CANCELLED,
    EventType.TASK_ERROR,
    EventType.MISSION_STEP_STARTED,
    EventType.MISSION_STEP_COMPLETED,
    EventType.MISSION_STEP_FAILED,
    EventType.MISSION_STEP_SKIPPED,
    EventType.MISSION_PLAN_CREATED,
    EventType.MISSION_COMPLETED,
    EventType.MISSION_FAILED,
}


def _event_type(event: Any) -> str:
    return str(getattr(event, "type", ""))


def _data(event: Any) -> dict[str, Any]:
    return getattr(event, "data", None) or {}


def _context_items(context: Any) -> list[ContextItem]:
    """What was gathered, and whether it reached the agent.

    A workspace that was checked but not made active is reported as gathered
    and *not* provided — the distinction §8 asks for, and the only one the
    system can actually prove.
    """
    items: list[ContextItem] = []
    if context is None:
        return items

    for memory in getattr(context, "memories", ())[:6]:
        items.append(
            ContextItem.build(
                kind="memory",
                label=f"{memory.type} {memory.key}",
                provided=True,
                detail=str(memory.value),
                reason=explain.why_memory(memory),
            )
        )

    for workspace in getattr(context, "workspaces", ())[:3]:
        detail = workspace.path
        if workspace.git_branch:
            changed = (
                f", {workspace.changed_files} changed"
                if workspace.changed_files
                else ", clean"
            )
            detail = f"{workspace.path} · {workspace.git_branch}{changed}"
        items.append(
            ContextItem.build(
                kind="workspace",
                label="Active workspace" if workspace.active else "Candidate workspace",
                provided=bool(workspace.active),
                detail=detail,
                reason=explain.why_workspace(workspace),
            )
        )

    processes = getattr(context, "processes", ())
    if processes:
        running = [p for p in processes if p.status == "RUNNING"]
        items.append(
            ContextItem.build(
                kind="processes",
                label=f"{len(processes)} managed process(es)",
                provided=True,
                detail=", ".join(f"{p.name} ({p.status})" for p in processes[:3]),
                reason=(
                    f"{len(running)} running when this request was answered."
                    if running
                    else "None were running when this request was answered."
                ),
            )
        )

    observations = getattr(context, "observations", ())
    if observations:
        items.append(
            ContextItem.build(
                kind="observations",
                label=f"{len(observations)} recent observation(s)",
                provided=True,
                reason=explain.why_observation(),
            )
        )

    if getattr(context, "machine", None):
        items.append(
            ContextItem.build(
                kind="machine",
                label="Machine details",
                provided=True,
                detail=context.machine.to_line().lstrip("- "),
                reason="Included for requests that mention this Mac.",
            )
        )

    return items


def _permission_outcome(events: list[Any], tool: str) -> tuple[str, str]:
    """Whether an approval request was answered, and how.

    Derived from what followed it: a tool that started after being requested
    was approved; one that never started was not. The broker's own decision is
    not on the event stream, so this reads the consequence rather than
    asserting a state nobody recorded.
    """
    started = any(
        _event_type(e) == EventType.TOOL_STARTED and e.tool == tool for e in events
    )
    if started:
        return Mark.OK, "You approved it."
    cancelled = any(_event_type(e) == EventType.TASK_CANCELLED for e in events)
    if cancelled:
        return Mark.SKIPPED, "The task was cancelled before you decided."
    return Mark.DENIED, "It did not run — the request was declined or expired."


def build(record: Any, *, context: Any = None, registry: Any = None) -> Trace:
    """Project one task record into a trace. Never raises."""
    events = list(getattr(record, "events", []) or [])
    steps: list[TraceStep] = []
    evidence: list[EvidenceItem] = []
    tools_run: list[str] = []
    approved = 0
    denied = 0
    outcome: str | None = None
    outcome_reason = ""
    cancelled = False

    for event in events:
        kind = _event_type(event)
        if kind not in {str(e) for e in _STEP_EVENTS}:
            continue
        data = _data(event)
        stamp = getattr(event, "timestamp", "")
        tool = getattr(event, "tool", None)

        if kind == EventType.TOOL_REQUESTED:
            definition = registry.get(tool) if registry is not None else None
            steps.append(
                TraceStep.build(
                    phase=Phase.ACTION,
                    label=f"{tool} requested",
                    mark=Mark.INFO,
                    detail=explain.why_tool(tool, definition),
                    reason=explain.why_permission(tool, data.get("permission", "")),
                    tool=tool,
                    timestamp=stamp,
                )
            )

        elif kind == EventType.PERMISSION_REQUIRED:
            mark, reason = _permission_outcome(events, tool)
            if mark is Mark.OK:
                approved += 1
            elif mark is Mark.DENIED:
                denied += 1
            steps.append(
                TraceStep.build(
                    phase=Phase.APPROVAL,
                    label="Your approval was required",
                    mark=Mark.WAITING if mark is Mark.SKIPPED else mark,
                    detail=getattr(event, "message", "") or "",
                    reason=reason,
                    tool=tool,
                    timestamp=stamp,
                )
            )

        elif kind == EventType.TOOL_STARTED:
            tools_run.append(tool)
            steps.append(
                TraceStep.build(
                    phase=Phase.ACTION,
                    label=f"{tool} ran",
                    mark=Mark.INFO,
                    tool=tool,
                    timestamp=stamp,
                )
            )

        elif kind == EventType.TOOL_COMPLETED:
            success = bool(data.get("success", True))
            steps.append(
                TraceStep.build(
                    phase=Phase.ACTION,
                    label=f"{tool} returned",
                    mark=Mark.OK if success else Mark.FAILED,
                    detail=getattr(event, "message", "") or "",
                    reason=(
                        "The tool returned. This alone does not establish that "
                        "the goal was met."
                        if success
                        else "The tool reported a failure."
                    ),
                    tool=tool,
                    timestamp=stamp,
                )
            )

        elif kind == EventType.VERIFICATION_STARTED:
            steps.append(
                TraceStep.build(
                    phase=Phase.VERIFICATION,
                    label=f"Checking whether {tool} worked",
                    mark=Mark.INFO,
                    reason="Read-only checks, using SAFE tools only.",
                    tool=tool,
                    timestamp=stamp,
                )
            )

        elif kind == EventType.VERIFICATION_COMPLETED:
            found = str(data.get("outcome") or "UNKNOWN")
            statements = [s for s in (data.get("evidence") or []) if s]
            unknowns = [u for u in (data.get("unknowns") or []) if u]
            outcome = found
            # Statements come off an event, so clean them before they are
            # composed into a sentence rather than only after.
            statements = [clean(s, MAX_TRACE_CHARS) for s in statements]
            unknowns = [clean(u, MAX_TRACE_CHARS) for u in unknowns]
            outcome_reason = explain.why_outcome(found, statements, unknowns)
            evidence.extend(
                EvidenceItem.build(statement=s, source=tool or "verifier")
                for s in statements
            )
            for statement in statements:
                steps.append(
                    TraceStep.build(
                        phase=Phase.VERIFICATION,
                        label=statement,
                        mark=Mark.FAILED if found == "FAILED" else Mark.OK,
                        tool=tool,
                        timestamp=stamp,
                    )
                )
            for statement in unknowns:
                steps.append(
                    TraceStep.build(
                        phase=Phase.VERIFICATION,
                        label=statement,
                        mark=Mark.SKIPPED,
                        reason="Not established by any check.",
                        tool=tool,
                        timestamp=stamp,
                    )
                )
            steps.append(
                TraceStep.build(
                    phase=Phase.OUTCOME,
                    label=found,
                    mark=Mark.OK if found == "SUCCESS" else (
                        Mark.FAILED if found == "FAILED" else Mark.SKIPPED
                    ),
                    reason=outcome_reason,
                    tool=tool,
                    timestamp=stamp,
                )
            )

        elif kind == EventType.TASK_CANCELLED:
            cancelled = True
            steps.append(
                TraceStep.build(
                    phase=Phase.OUTCOME,
                    label="Cancelled",
                    mark=Mark.SKIPPED,
                    reason="You stopped the task before it finished.",
                    timestamp=stamp,
                )
            )

        elif kind == EventType.TASK_ERROR:
            steps.append(
                TraceStep.build(
                    phase=Phase.OUTCOME,
                    label="The request failed",
                    mark=Mark.FAILED,
                    detail=getattr(event, "message", "") or "",
                    timestamp=stamp,
                )
            )

        else:  # mission lifecycle
            failed = kind in (EventType.MISSION_STEP_FAILED, EventType.MISSION_FAILED)
            skipped = kind == EventType.MISSION_STEP_SKIPPED
            steps.append(
                TraceStep.build(
                    phase=Phase.MISSION,
                    label=getattr(event, "message", "") or kind.replace("_", " "),
                    mark=Mark.FAILED if failed else (Mark.SKIPPED if skipped else Mark.OK),
                    reason=str(data.get("reason") or ""),
                    timestamp=stamp,
                )
            )

    context_items = _context_items(context)
    if context_items:
        steps.insert(
            0,
            TraceStep.build(
                phase=Phase.CONTEXT,
                label=f"Gathered {len(context_items)} piece(s) of context",
                mark=Mark.INFO,
                reason="Collected with SAFE tools before the agent ran.",
                timestamp=getattr(record, "created_at", ""),
            ),
        )

    return Trace(
        task_id=getattr(record, "task_id", ""),
        request=getattr(record, "request", "")[:400],
        status=str(getattr(record, "status", "")),
        summary=explain.summarise(
            tools_run=tools_run,
            approved=approved,
            denied=denied,
            outcome=outcome,
            context_kinds=[c.kind for c in context_items if c.provided],
            cancelled=cancelled,
        ),
        context=tuple(context_items),
        steps=tuple(steps[:MAX_TRACE_ITEMS]),
        evidence=tuple(evidence[:MAX_EVIDENCE_PER_TRACE]),
        outcome=outcome,
        outcome_reason=outcome_reason,
        created_at=getattr(record, "created_at", ""),
        completed_at=getattr(record, "completed_at", None),
    )


def safe_build(record: Any, *, context: Any = None, registry: Any = None) -> Trace | None:
    """Build a trace, or return None. Explainability is never load-bearing."""
    try:
        return build(record, context=context, registry=registry)
    except Exception:  # noqa: BLE001 - a trace failure must not surface anywhere
        logger.warning("Could not build a trace", exc_info=True)
        return None


__all__ = ["build", "safe_build"]
