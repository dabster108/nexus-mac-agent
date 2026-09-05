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
            scores={"completion": 1.0, "latency": 0.9},
            latency_ms=1200,
        ),
        EvalResult(
            case_id="refusal_test",
            status="completed",
            scores={"completion": 1.0, "safety": 1.0},
            latency_ms=800,
            error=None,
        ),
    ]
    path = write_markdown_report(
        results,
        dataset="core",
        path=tmp_path / "core.md",
        dry_run=True,
        nexus_api_url="http://127.0.0.1:8000",
    )
    text = path.read_text()
    assert "dry-run" in text
    assert "battery_check" in text
    assert "overall" in text
