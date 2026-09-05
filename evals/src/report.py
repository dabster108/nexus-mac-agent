"""Local reports for dry-run (and as a companion to Langfuse runs)."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path

from src.runner import EvalResult


def write_markdown_report(
    results: Sequence[EvalResult],
    *,
    dataset: str,
    path: Path,
    dry_run: bool,
    nexus_api_url: str,
) -> Path:
    """Write a human-readable scorecard next to the JSON results."""
    path.parent.mkdir(parents=True, exist_ok=True)
    now = datetime.now(UTC).strftime("%Y-%m-%d %H:%M:%S UTC")
    total_scores: dict[str, float] = {}
    for r in results:
        for k, v in r.scores.items():
            total_scores[k] = total_scores.get(k, 0.0) + v
    n = len(results) or 1

    lines = [
        f"# NEXUS eval — `{dataset}`",
        "",
        f"- When: {now}",
        f"- Backend: `{nexus_api_url}`",
        f"- Mode: {'dry-run (local only)' if dry_run else 'Langfuse + local'}",
        f"- Cases: {len(results)}",
        "",
        "## Aggregate",
        "",
        "| Score | Mean |",
        "| --- | ---: |",
    ]
    for k, v in sorted(total_scores.items()):
        lines.append(f"| `{k}` | {v / n:.2f} |")
    overall = sum(total_scores.values()) / (len(total_scores) * n) if total_scores else 0.0
    lines.append(f"| **overall** | **{overall:.2f}** |")
    lines.extend(["", "## Cases", ""])
    lines.append("| Case | Status | Tools | Avg | Latency |")
    lines.append("| --- | --- | --- | ---: | ---: |")

    for r in results:
        avg = sum(r.scores.values()) / len(r.scores) if r.scores else 0.0
        tools = ", ".join(r.tools_called) if r.tools_called else "—"
        mark = "✓" if r.status == "completed" else "✗"
        lines.append(
            f"| {mark} `{r.case_id}` | `{r.status}` | {tools} | {avg:.2f} | {r.latency_ms:.0f}ms |"
        )
        if r.error:
            lines.append(f"|  | ⚠ {r.error} |  |  |  |")

    lines.append("")
    path.write_text("\n".join(lines))
    return path
