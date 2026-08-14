"""Turns a memory tool call into the richer memory_* events.

Not a second event system — these are ordinary :class:`ExecutionEvent`
instances, published through the same :class:`~app.agent.tasks.TaskStore`
every other event uses. This module only knows how to *describe* a memory
proposal or outcome; the runner and mission engine call it at the two points
where they already have the information: when a CONFIRM request for
``save_memory``/``delete_memory`` is created, and after a tool call finishes.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from app.agent import events as ev
from app.agent.events import EventSink

#: The two CONFIRM tools this module adds narration for.
MEMORY_CONFIRM_TOOLS = frozenset({"save_memory", "delete_memory"})


def describe_proposal(tool: str, arguments: dict[str, Any]) -> str:
    """A human-readable description of what a memory CONFIRM call would do."""
    if tool == "save_memory":
        type_ = arguments.get("type", "fact")
        key = arguments.get("key", "")
        value = arguments.get("value", {})
        return f"Remember this {type_}: {key} = {value}"
    if tool == "delete_memory":
        if arguments.get("wipe_all"):
            return "Permanently delete every remembered fact."
        if arguments.get("memory_id"):
            return f"Forget the memory with id {arguments['memory_id']}."
        if arguments.get("key"):
            return f"Forget the memory with key '{arguments['key']}'."
        if arguments.get("key_contains"):
            return f"Forget every memory whose key contains '{arguments['key_contains']}'."
        if arguments.get("type"):
            return f"Forget every {arguments['type']} memory."
        return "Forget a remembered fact."
    return f"Run {tool}."  # pragma: no cover - defensive, tool set is fixed above


def emit_memory_outcome_events(
    tool_results: Sequence[dict[str, Any]], task_id: str, emit: EventSink
) -> None:
    """After a graph run finishes, narrate any memory writes it made."""
    for result in tool_results:
        name = result.get("name")
        if name not in MEMORY_CONFIRM_TOOLS or not result.get("success"):
            continue
        structured = result.get("structured")
        if not isinstance(structured, dict):
            continue

        if name == "save_memory":
            saved = structured.get("memory") or {}
            if saved.get("id"):
                emit(ev.memory_saved(task_id, saved["id"], saved.get("key", "")))
        elif name == "delete_memory":
            count = structured.get("count", 0)
            keys = structured.get("deleted_keys") or []
            description = f"Forgot {count} memor{'y' if count == 1 else 'ies'}"
            if keys:
                description += f": {', '.join(keys)}"
            emit(ev.memory_deleted(task_id, count, description))
