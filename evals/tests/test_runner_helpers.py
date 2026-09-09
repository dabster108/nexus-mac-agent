"""Runner helper unit tests (no network)."""

from __future__ import annotations

from src.runner import _outcome_from_trace, _tools_from_events


def test_tools_from_events_dedupes() -> None:
    events = [
        {"type": "tool_started", "tool": "battery_status"},
        {"type": "tool_completed", "tool": "battery_status"},
        {"type": "tool_started", "tool": "battery_status"},
        {"type": "tool_started", "tool": "system_info"},
    ]
    assert _tools_from_events(events) == ["battery_status", "system_info"]


def test_outcome_from_trace_prefers_trace() -> None:
    assert _outcome_from_trace({"outcome": "SUCCESS"}, []) == "SUCCESS"
    events = [
        {"type": "verification_completed", "data": {"outcome": "FAILED"}},
    ]
    assert _outcome_from_trace({}, events) == "FAILED"
