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


def load_dataset(name: str) -> list[EvalCase]:
    """Load a named YAML dataset from evals/datasets/<name>.yaml."""
    path = DATASETS_DIR / f"{name}.yaml"
    if not path.exists():
        raise FileNotFoundError(f"Dataset not found: {path}")

    raw = yaml.safe_load(path.read_text())
    cases: list[EvalCase] = []
    for item in raw.get("cases", []):
        cases.append(
            EvalCase(
                id=item["id"],
                input=item["input"],
                expected_tools=item.get("expected_tools", []),
                expected_outcome=item.get("expected_outcome", "SUCCESS"),
                expected_keywords=item.get("expected_keywords", []),
                tags=item.get("tags", []),
                metadata=item.get("metadata", {}),
            )
        )
    return cases


def list_datasets() -> list[str]:
    """Return names of all available datasets."""
    return sorted(p.stem for p in DATASETS_DIR.glob("*.yaml"))
