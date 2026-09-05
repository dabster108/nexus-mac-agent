"""Dataset loading tests."""

from __future__ import annotations

from src.dataset import list_datasets, load_dataset


def test_core_dataset_loads() -> None:
    assert "core" in list_datasets()
    cases = load_dataset("core")
    assert len(cases) >= 8
    ids = {c.id for c in cases}
    assert "battery_check" in ids
    assert "confirm_gate_test" in ids
    assert "refusal_test" in ids


def test_confirm_case_requires_approval() -> None:
    confirm = next(c for c in load_dataset("core") if c.id == "confirm_gate_test")
    assert confirm.metadata.get("requires_approval") is True
    assert "open_application" in confirm.expected_tools
