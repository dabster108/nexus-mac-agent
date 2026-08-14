"""describe_proposal / emit_memory_outcome_events: narration for memory writes."""

from __future__ import annotations

from app.agent.events import EventType, ExecutionEvent
from app.context.memory_events import describe_proposal, emit_memory_outcome_events


class _Recorder:
    def __init__(self) -> None:
        self.events: list[ExecutionEvent] = []

    def __call__(self, event: ExecutionEvent) -> None:
        self.events.append(event)


# --- describe_proposal -----------------------------------------------------


def test_describes_a_save() -> None:
    description = describe_proposal(
        "save_memory", {"type": "PROJECT", "key": "nexus", "value": {"path": "~/nexus"}}
    )

    assert "nexus" in description
    assert "~/nexus" in description


def test_describes_a_delete_by_id() -> None:
    assert "mem_123" in describe_proposal("delete_memory", {"memory_id": "mem_123"})


def test_describes_a_delete_by_key() -> None:
    assert "backend" in describe_proposal("delete_memory", {"key": "backend"})


def test_describes_a_scoped_bulk_delete() -> None:
    description = describe_proposal("delete_memory", {"key_contains": "nexus"})

    assert "nexus" in description


def test_describes_a_type_delete() -> None:
    assert "PROJECT" in describe_proposal("delete_memory", {"type": "PROJECT"})


def test_describes_wipe_all_distinctly() -> None:
    description = describe_proposal("delete_memory", {"wipe_all": True})

    assert "every" in description.lower() or "all" in description.lower()
    assert "permanently" in description.lower()


def test_a_bare_delete_with_no_filter_still_describes_something() -> None:
    assert describe_proposal("delete_memory", {})


# --- emit_memory_outcome_events ---------------------------------------------


def test_a_successful_save_emits_memory_saved() -> None:
    emit = _Recorder()
    results = [
        {
            "name": "save_memory", "success": True,
            "structured": {"success": True, "memory": {"id": "mem_1", "key": "nexus"}},
        }
    ]

    emit_memory_outcome_events(results, "task_1", emit)

    assert len(emit.events) == 1
    assert emit.events[0].type is EventType.MEMORY_SAVED
    assert emit.events[0].data["memory_id"] == "mem_1"
    assert emit.events[0].data["key"] == "nexus"


def test_a_successful_delete_emits_memory_deleted() -> None:
    emit = _Recorder()
    results = [
        {
            "name": "delete_memory", "success": True,
            "structured": {"success": True, "count": 2, "deleted_keys": ["a", "b"]},
        }
    ]

    emit_memory_outcome_events(results, "task_1", emit)

    assert emit.events[0].type is EventType.MEMORY_DELETED
    assert emit.events[0].data["count"] == 2
    assert "a" in emit.events[0].message
    assert "b" in emit.events[0].message


def test_a_failed_call_emits_nothing() -> None:
    emit = _Recorder()
    results = [{"name": "save_memory", "success": False, "structured": {"success": False}}]

    emit_memory_outcome_events(results, "task_1", emit)

    assert emit.events == []


def test_unrelated_tool_results_are_ignored() -> None:
    emit = _Recorder()
    results = [{"name": "git_status", "success": True, "structured": {"success": True}}]

    emit_memory_outcome_events(results, "task_1", emit)

    assert emit.events == []


def test_a_result_without_structured_content_is_ignored() -> None:
    emit = _Recorder()
    results = [{"name": "save_memory", "success": True, "structured": None}]

    emit_memory_outcome_events(results, "task_1", emit)

    assert emit.events == []


def test_multiple_results_each_produce_an_event() -> None:
    emit = _Recorder()
    results = [
        {"name": "save_memory", "success": True, "structured": {"memory": {"id": "mem_1", "key": "a"}}},
        {"name": "save_memory", "success": True, "structured": {"memory": {"id": "mem_2", "key": "b"}}},
    ]

    emit_memory_outcome_events(results, "task_1", emit)

    assert len(emit.events) == 2
