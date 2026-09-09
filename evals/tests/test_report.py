"""Local markdown report."""

from __future__ import annotations

from pathlib import Path

from src.report import write_markdown_report
from src.runner import EvalResult


def test_markdown_report(tmp_path: Path) -> None:
    results = [
        EvalResult(
            case_id="battery_check",
            status="completed",
            tools_called=["battery_status"],
            scores={
                "tool_selection": 1.0,
                "outcome": 1.0,
                "keywords": 1.0,
                "completion": 1.0,
                "latency": 0.9,
                "safety": 1.0,
            },
            latency_ms=1200,
        ),
        EvalResult(
            case_id="refusal_test",
            status="completed",
            scores={
                "tool_selection": 1.0,
                "outcome": 1.0,
                "keywords": 1.0,
                "completion": 1.0,
                "latency": 1.0,
                "safety": 1.0,
            },
            latency_ms=800,
            error=None,
        ),
    ]
    path = write_markdown_report(
        results,
        dataset="smoke",
        path=tmp_path / "smoke.md",
        dry_run=True,
        nexus_api_url="http://127.0.0.1:8000",
        run_name="smoke-test",
        dataset_version="1",
    )
    text = path.read_text()
    assert "dry-run" in text
    assert "battery_check" in text
    assert "overall" in text
    assert "smoke-test" in text
    assert "excludes diagnostic" in text


def test_run_envelope_schema(tmp_path: Path) -> None:
    from src.report import build_run_envelope

    results = [
        EvalResult(
            case_id="battery_check",
            status="completed",
            scores={
                "tool_selection": 1.0,
                "outcome": 1.0,
                "keywords": 1.0,
                "completion": 1.0,
                "latency": 0.5,
                "safety": 1.0,
            },
        )
    ]
    envelope = build_run_envelope(
        results,
        dataset="smoke",
        dataset_version="1",
        run_name="smoke-1",
        nexus_api_url="http://127.0.0.1:8000",
        dry_run=True,
        auto_approve=False,
        started_at="2026-01-01T00:00:00+00:00",
    )
    assert envelope["schema"] == "nexus-evals/v1"
    assert envelope["passed"] == 1
    assert "latency" in envelope["aggregates"]
    assert envelope["aggregates"]["overall"] == 1.0
    (tmp_path / "env.json").write_text(__import__("json").dumps(envelope))
