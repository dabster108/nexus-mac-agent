"""CLI entry point for the NEXUS eval harness.

Usage:
    cd evals
    uv run python -m src                          # run all cases in 'core'
    uv run python -m src --dataset core            # explicit dataset
    uv run python -m src --dataset core --approve  # auto-approve CONFIRM tools
    uv run python -m src --list                    # list available datasets
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

from src.client import flush
from src.config import EvalConfig
from src.dataset import list_datasets, load_dataset
from src.runner import run_dataset


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="nexus-evals",
        description="Run evaluation cases against a live NEXUS backend and trace to Langfuse.",
    )
    p.add_argument(
        "--dataset", "-d",
        default="core",
        help="Name of the dataset file in evals/datasets/ (default: core)",
    )
    p.add_argument(
        "--approve",
        action="store_true",
        help="Auto-approve CONFIRM tool requests during eval",
    )
    p.add_argument(
        "--concurrency", "-c",
        type=int,
        default=1,
        help="Max concurrent eval cases (default: 1)",
    )
    p.add_argument(
        "--output", "-o",
        type=str,
        default=None,
        help="Write results JSON to this path (default: results/<dataset>.json)",
    )
    p.add_argument(
        "--list",
        action="store_true",
        dest="list_datasets",
        help="List available datasets and exit",
    )
    return p


def main() -> None:
    args = _build_parser().parse_args()

    if args.list_datasets:
        datasets = list_datasets()
        if not datasets:
            print("No datasets found in evals/datasets/")
        else:
            print("Available datasets:")
            for name in datasets:
                print(f"  • {name}")
        return

    config = EvalConfig.from_env()
    cases = load_dataset(args.dataset)
    print(f"▸ Running {len(cases)} case(s) from '{args.dataset}' against {config.nexus_api_url}")
    print(f"  Langfuse: {config.langfuse_host}")
    print(f"  Auto-approve: {args.approve}")
    print()

    results = asyncio.run(
        run_dataset(
            cases,
            config,
            auto_approve=args.approve,
            concurrency=args.concurrency,
        )
    )

    # --- Print summary table -------------------------------------------
    total_scores: dict[str, float] = {}
    count = 0

    for r in results:
        status_icon = "✓" if r.status == "completed" else "✗"
        tools_str = ", ".join(r.tools_called) if r.tools_called else "—"
        avg = sum(r.scores.values()) / len(r.scores) if r.scores else 0.0
        print(f"  {status_icon} {r.case_id:<28} {r.status:<12} tools=[{tools_str}]  avg={avg:.2f}  {r.latency_ms:.0f}ms")

        if r.error:
            print(f"    ⚠ {r.error}")

        for k, v in r.scores.items():
            total_scores[k] = total_scores.get(k, 0.0) + v
        count += 1

    print()
    if count:
        print("  Aggregate scores:")
        for k, v in sorted(total_scores.items()):
            print(f"    {k:<20} {v / count:.2f}")
        overall = sum(total_scores.values()) / (len(total_scores) * count) if total_scores else 0.0
        print(f"    {'overall':<20} {overall:.2f}")

    # --- Write results JSON -------------------------------------------
    out_path = Path(args.output) if args.output else Path("results") / f"{args.dataset}.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(
        json.dumps(
            [
                {
                    "case_id": r.case_id,
                    "task_id": r.task_id,
                    "status": r.status,
                    "tools_called": r.tools_called,
                    "outcome": r.outcome,
                    "scores": r.scores,
                    "latency_ms": r.latency_ms,
                    "error": r.error,
                }
                for r in results
            ],
            indent=2,
        )
    )
    print(f"\n  Results written to {out_path}")

    flush()
    print("  Langfuse events flushed ✓")


if __name__ == "__main__":
    main()
