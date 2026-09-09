"""Aggregate helpers."""

from __future__ import annotations

from src.aggregates import aggregate_scores, case_average, passed_case
from src.runner import EvalResult


def test_overall_excludes_latency() -> None:
    results = [
        EvalResult(
            case_id="a",
            status="completed",
            scores={
                "tool_selection": 1.0,
                "outcome": 1.0,
                "keywords": 1.0,
                "completion": 1.0,
                "latency": 0.0,
                "safety": 1.0,
            },
        )
    ]
    means = aggregate_scores(results)
    assert means["latency"] == 0.0
    assert means["overall"] == 1.0
    assert case_average(results[0].scores) == 1.0
    assert passed_case(results[0]) is True


def test_failed_case() -> None:
    bad = EvalResult(case_id="b", status="error", scores={"completion": 0.0, "safety": 1.0})
    assert passed_case(bad) is False
