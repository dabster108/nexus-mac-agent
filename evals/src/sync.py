"""Sync local YAML datasets into Langfuse Datasets.

Stable item ids (`nexus-{dataset}-{case_id}`) make re-sync an upsert, so the
Langfuse UI always matches ``evals/datasets/*.yaml`` without duplicates.

Traces carry ``dataset_item_id`` metadata for filtering; membership in a
Langfuse Dataset Run is tag-based (`run:<name>`) rather than a hard SDK link.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from src.client import get_langfuse
from src.config import EvalConfig
from src.dataset import EvalCase, load_eval_dataset


def langfuse_dataset_name(local_name: str) -> str:
    """Langfuse dataset name for a local YAML stem."""
    return f"nexus-evals-{local_name}"


def item_id(local_name: str, case_id: str) -> str:
    return f"nexus-{local_name}-{case_id}"


def _expected_output(case: EvalCase) -> dict[str, Any]:
    return {
        "expected_tools": case.expected_tools,
        "expected_outcome": case.expected_outcome,
        "expected_keywords": case.expected_keywords,
    }


def _item_metadata(case: EvalCase, *, dataset_version: str) -> dict[str, Any]:
    return {
        "case_id": case.id,
        "tags": case.tags,
        "dataset_version": dataset_version,
        **case.metadata,
    }


@dataclass(frozen=True, slots=True)
class SyncResult:
    dataset: str
    total: int
    version: str


def ensure_dataset(config: EvalConfig, local_name: str, *, version: str) -> str:
    """Create the Langfuse dataset if missing. Returns the remote name."""
    langfuse = get_langfuse(config)
    remote = langfuse_dataset_name(local_name)
    try:
        langfuse.get_dataset(remote)
    except Exception:
        langfuse.create_dataset(
            name=remote,
            description=f"NEXUS eval cases from evals/datasets/{local_name}.yaml",
            metadata={
                "source": "evals/datasets",
                "local_name": local_name,
                "dataset_version": version,
            },
        )
    return remote


def sync_dataset(config: EvalConfig, local_name: str) -> SyncResult:
    """Upsert every local case into the matching Langfuse dataset."""
    config.require_langfuse()
    dataset = load_eval_dataset(local_name)
    remote = ensure_dataset(config, local_name, version=dataset.version)
    langfuse = get_langfuse(config)

    for case in dataset.cases:
        langfuse.create_dataset_item(
            dataset_name=remote,
            id=item_id(local_name, case.id),
            input={"message": case.input},
            expected_output=_expected_output(case),
            metadata=_item_metadata(case, dataset_version=dataset.version),
        )

    langfuse.flush()
    return SyncResult(dataset=remote, total=len(dataset.cases), version=dataset.version)
