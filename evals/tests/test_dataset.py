"""Dataset loading tests."""

from __future__ import annotations

from src.dataset import list_datasets, load_dataset


def test_core_dataset_loads() -> None:
    assert "core" in list_datasets()
    assert "smoke" in list_datasets()
    cases = load_dataset("core")
    assert len(cases) >= 8
    ids = {c.id for c in cases}
    assert "battery_check" in ids
    assert "confirm_gate_test" in ids
    assert "refusal_test" in ids


def test_smoke_dataset_is_small() -> None:
    from src.dataset import load_eval_dataset

    dataset = load_eval_dataset("smoke")
    assert dataset.version == "1"
    assert 3 <= len(dataset.cases) <= 5
    assert all("smoke" in c.tags for c in dataset.cases)


def test_duplicate_ids_rejected(tmp_path, monkeypatch) -> None:
    from src import dataset as dataset_mod

    bad = tmp_path / "bad.yaml"
    bad.write_text(
        "version: '1'\ncases:\n  - id: a\n    input: one\n  - id: a\n    input: two\n"
    )
    monkeypatch.setattr(dataset_mod, "DATASETS_DIR", tmp_path)
    import pytest

    with pytest.raises(ValueError, match="duplicate"):
        dataset_mod.load_eval_dataset("bad")


def test_confirm_case_requires_approval() -> None:
    confirm = next(c for c in load_dataset("core") if c.id == "confirm_gate_test")
    assert confirm.metadata.get("requires_approval") is True
    assert "open_application" in confirm.expected_tools
