"""Dataset sync helpers (no network)."""

from __future__ import annotations

from src.sync import item_id, langfuse_dataset_name


def test_langfuse_naming() -> None:
    assert langfuse_dataset_name("smoke") == "nexus-evals-smoke"
    assert item_id("smoke", "battery_check") == "nexus-smoke-battery_check"
