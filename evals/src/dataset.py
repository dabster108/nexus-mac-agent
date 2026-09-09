"""Load and validate eval datasets (YAML files in evals/datasets/)."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

DATASETS_DIR = Path(__file__).resolve().parent.parent / "datasets"


@dataclass(slots=True)
class EvalCase:
    """One evaluation case."""

    id: str
    input: str
    expected_tools: list[str] = field(default_factory=list)
    expected_outcome: str = "SUCCESS"
    expected_keywords: list[str] = field(default_factory=list)
    tags: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class EvalDataset:
    """A named, versioned set of cases loaded from one YAML file."""

    name: str
    version: str
    cases: tuple[EvalCase, ...]
    path: Path

    def __len__(self) -> int:
        return len(self.cases)


def load_dataset(name: str) -> list[EvalCase]:
    """Load cases from ``evals/datasets/<name>.yaml`` (compat wrapper)."""
    return list(load_eval_dataset(name).cases)


def load_eval_dataset(name: str) -> EvalDataset:
    """Load and validate a named YAML dataset."""
    path = DATASETS_DIR / f"{name}.yaml"
    if not path.exists():
        raise FileNotFoundError(f"Dataset not found: {path}")

    raw = yaml.safe_load(path.read_text())
    if not isinstance(raw, dict):
        raise ValueError(f"Dataset {path} must be a mapping with a 'cases' list")

    version = str(raw.get("version") or "0").strip() or "0"
    items = raw.get("cases")
    if not isinstance(items, list) or not items:
        raise ValueError(f"Dataset {path} needs a non-empty 'cases' list")

    cases: list[EvalCase] = []
    seen: set[str] = set()
    for index, item in enumerate(items):
        if not isinstance(item, dict):
            raise ValueError(f"Dataset {path} case #{index} must be a mapping")
        case_id = str(item.get("id") or "").strip()
        prompt = item.get("input")
        if not case_id:
            raise ValueError(f"Dataset {path} case #{index} is missing 'id'")
        if not isinstance(prompt, str) or not prompt.strip():
            raise ValueError(f"Dataset {path} case '{case_id}' is missing 'input'")
        if case_id in seen:
            raise ValueError(f"Dataset {path} has duplicate case id '{case_id}'")
        seen.add(case_id)
        cases.append(
            EvalCase(
                id=case_id,
                input=prompt.strip(),
                expected_tools=list(item.get("expected_tools") or []),
                expected_outcome=str(item.get("expected_outcome") or "SUCCESS"),
                expected_keywords=list(item.get("expected_keywords") or []),
                tags=list(item.get("tags") or []),
                metadata=dict(item.get("metadata") or {}),
            )
        )

    return EvalDataset(name=name, version=version, cases=tuple(cases), path=path)


def list_datasets() -> list[str]:
    """Return names of all available datasets."""
    return sorted(p.stem for p in DATASETS_DIR.glob("*.yaml"))
