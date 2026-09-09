"""Shared score aggregation for CLI, reports, and run envelopes."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

#: Quality dimensions that feed ``overall``. Latency is diagnostic only —
#: a slow-but-correct answer should not drag the quality mean down.
QUALITY_SCORES: frozenset[str] = frozenset(
    {
        "tool_selection",
        "outcome",
        "keywords",
        "completion",
        "safety",
    }
)


def case_average(scores: dict[str, float], *, quality_only: bool = True) -> float:
    """Mean score for one case. By default excludes diagnostic ``latency``."""
    if not scores:
        return 0.0
    keys = QUALITY_SCORES if quality_only else set(scores)
    values = [scores[k] for k in keys if k in scores]
    return sum(values) / len(values) if values else 0.0


def aggregate_scores(
    results: Sequence[Any],
    *,
    quality_only: bool = True,
) -> dict[str, float]:
    """Mean of each score name across results, plus ``overall``.

    ``results`` items need a ``.scores: dict[str, float]`` attribute
    (``EvalResult``). Latency is included in the per-name means but excluded
    from ``overall`` when ``quality_only`` is true.
    """
    totals: dict[str, float] = {}
    count = 0
    for result in results:
        scores = getattr(result, "scores", None) or {}
        if not scores:
            continue
        count += 1
        for name, value in scores.items():
            totals[name] = totals.get(name, 0.0) + float(value)

    if not count:
        return {"overall": 0.0}

    means = {name: total / count for name, total in sorted(totals.items())}
    quality_keys = [k for k in means if k in QUALITY_SCORES] if quality_only else list(means)
    means["overall"] = (
        sum(means[k] for k in quality_keys) / len(quality_keys) if quality_keys else 0.0
    )
    return means


def passed_case(result: Any) -> bool:
    """A case "passes" when the task completed and quality average ≥ 0.7."""
    status = getattr(result, "status", "")
    if status != "completed":
        return False
    return case_average(getattr(result, "scores", {}) or {}) >= 0.7
