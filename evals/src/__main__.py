"""CLI entry point for the NEXUS eval harness.

Usage:
    cd evals
    uv run python -m src --check
    uv run python -m src --sync -d smoke
    uv run python -m src -d smoke --approve
    uv run python -m src --dry-run --approve
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

from src.aggregates import aggregate_scores, case_average, passed_case
from src.client import check_auth, flush, shutdown
from src.config import EvalConfig
from src.dataset import list_datasets, load_eval_dataset
from src.report import build_run_envelope, write_markdown_report
from src.runner import check_backend, run_dataset
from src.sync import sync_dataset


def _default_run_name(dataset: str) -> str:
    stamp = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
    return f"{dataset}-{stamp}"


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="nexus-evals",
        description=(
            "Run evaluation cases against a live NEXUS backend and record "
            "scores in Langfuse. Use --dry-run for local-only scoring."
        ),
    )
    p.add_argument(
        "--dataset",
        "-d",
        default="smoke",
        help="Dataset in evals/datasets/ (default: smoke). Use 'core' for the full set.",
    )
    p.add_argument(
        "--run-name",
        default=None,
        help="Name for this eval run (default: <dataset>-<timestamp>)",
    )
    p.add_argument(
        "--approve",
        action="store_true",
        help="Auto-approve CONFIRM tool requests during eval",
    )
    p.add_argument(
        "--dry-run",
        action="store_true",
        help="Score locally only — no Langfuse credentials required",
    )
    p.add_argument(
        "--sync",
        action="store_true",
        help="Upsert the local YAML dataset into Langfuse Datasets and exit",
    )
    p.add_argument(
        "--no-sync",
        action="store_true",
        help="Skip auto-syncing the dataset to Langfuse before a live run",
    )
    p.add_argument(
        "--concurrency",
        "-c",
        type=int,
        default=1,
        help="Max concurrent eval cases (default: 1)",
    )
    p.add_argument(
        "--output",
        "-o",
        type=str,
        default=None,
        help="Write run envelope JSON here (default: results/<run_name>.json)",
    )
    p.add_argument(
        "--list",
        action="store_true",
        dest="list_datasets",
        help="List available datasets and exit",
    )
    p.add_argument(
        "--check",
        action="store_true",
        help="Verify Langfuse credentials (auth_check) and exit",
    )
    p.add_argument(
        "--skip-health",
        action="store_true",
        help="Do not probe GET /health before running cases",
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

    config = EvalConfig.from_env(dry_run=args.dry_run)
    run_name = args.run_name or _default_run_name(args.dataset)

    if args.check:
        try:
            config.require_langfuse()
        except RuntimeError as exc:
            print(f"Config error: {exc}", file=sys.stderr)
            sys.exit(1)
        print(f"Checking Langfuse at {config.langfuse_host} …", flush=True)
        try:
            ok = check_auth(config)
        except Exception as exc:
            print(f"✗ Langfuse unreachable: {exc}", file=sys.stderr)
            sys.exit(1)
        finally:
            shutdown()
        if not ok:
            print(
                "✗ Credentials rejected — check LANGFUSE_PUBLIC_KEY / LANGFUSE_SECRET_KEY",
                file=sys.stderr,
            )
            sys.exit(1)
        print("✓ Langfuse auth ok")
        print(f"  host:        {config.langfuse_host}")
        print(f"  environment: {config.langfuse_environment}")
        print(f"  nexus api:   {config.nexus_api_url}")
        return

    if args.sync:
        if args.dry_run:
            print("Config error: --sync requires Langfuse (drop --dry-run)", file=sys.stderr)
            sys.exit(1)
        try:
            config.require_langfuse()
        except RuntimeError as exc:
            print(f"Config error: {exc}", file=sys.stderr)
            sys.exit(1)
        print(f"▸ Syncing dataset '{args.dataset}' → Langfuse …", flush=True)
        try:
            result = sync_dataset(config, args.dataset)
        except Exception as exc:
            print(f"✗ Sync failed: {exc}", file=sys.stderr)
            shutdown()
            sys.exit(1)
        flush()
        shutdown()
        print(
            f"  ✓ {result.total} item(s) upserted into `{result.dataset}` "
            f"(v{result.version})"
        )
        return

    if not args.dry_run:
        try:
            config.require_langfuse()
        except RuntimeError as exc:
            print(f"Config error: {exc}", file=sys.stderr)
            sys.exit(1)

    if not args.skip_health:
        print(f"▸ Checking backend at {config.nexus_api_url} …", flush=True)
        try:
            health = asyncio.run(check_backend(config))
        except Exception as exc:
            print(
                f"✗ Backend unreachable ({exc}). "
                "Start it with: cd backend && uv run uvicorn app.main:app "
                "--host 127.0.0.1 --port 8000",
                file=sys.stderr,
                flush=True,
            )
            sys.exit(1)
        print(f"  ✓ {health}", flush=True)

    if config.langfuse_enabled and not args.no_sync:
        print(f"▸ Syncing '{args.dataset}' to Langfuse before run …", flush=True)
        try:
            synced = sync_dataset(config, args.dataset)
            print(
                f"  ✓ {synced.total} item(s) in `{synced.dataset}` (v{synced.version})",
                flush=True,
            )
        except Exception as exc:
            print(f"  ⚠ dataset sync failed ({exc}); continuing with local cases", flush=True)

    try:
        dataset = load_eval_dataset(args.dataset)
    except (FileNotFoundError, ValueError) as exc:
        print(f"Dataset error: {exc}", file=sys.stderr)
        sys.exit(1)

    mode = (
        "dry-run (local scores only)"
        if config.dry_run
        else f"Langfuse → {config.langfuse_host} ({config.langfuse_environment})"
    )
    print(f"▸ Running {len(dataset.cases)} case(s) from '{args.dataset}' v{dataset.version}")
    print(f"  Backend: {config.nexus_api_url}")
    print(f"  Mode: {mode}")
    print(f"  Run: {run_name}")
    print(f"  Auto-approve: {args.approve}")
    print()

    started_at = datetime.now(UTC).isoformat()
    try:
        results = asyncio.run(
            run_dataset(
                list(dataset.cases),
                config,
                dataset_name=args.dataset,
                run_name=run_name,
                auto_approve=args.approve,
                concurrency=args.concurrency,
            )
        )
    except Exception:
        shutdown()
        raise

    aggregates = aggregate_scores(results)
    for r in results:
        mark = "✓" if passed_case(r) else "✗"
        tools_str = ", ".join(r.tools_called) if r.tools_called else "—"
        avg = case_average(r.scores)
        print(
            f"  {mark} {r.case_id:<28} {r.status:<20} "
            f"tools=[{tools_str}]  quality={avg:.2f}  {r.latency_ms:.0f}ms"
        )
        if r.error:
            print(f"    ⚠ {r.error}")
        if r.langfuse_trace_url:
            print(f"    ↗ {r.langfuse_trace_url}")

    print()
    print("  Aggregate scores (overall excludes latency):")
    for k, v in aggregates.items():
        print(f"    {k:<20} {v:.2f}")

    envelope = build_run_envelope(
        results,
        dataset=args.dataset,
        dataset_version=dataset.version,
        run_name=run_name,
        nexus_api_url=config.nexus_api_url,
        dry_run=config.dry_run,
        auto_approve=args.approve,
        started_at=started_at,
    )

    out_path = Path(args.output) if args.output else Path("results") / f"{run_name}.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(envelope, indent=2))
    alias = Path("results") / f"{args.dataset}.json"
    if args.output is None:
        alias.write_text(json.dumps(envelope, indent=2))

    md_path = out_path.with_suffix(".md")
    write_markdown_report(
        results,
        dataset=args.dataset,
        path=md_path,
        dry_run=config.dry_run,
        nexus_api_url=config.nexus_api_url,
        run_name=run_name,
        dataset_version=dataset.version,
        aggregates=aggregates,
    )
    print(f"\n  Results written to {out_path}")
    if args.output is None:
        print(f"  Alias written to   {alias}")
    print(f"  Report written to  {md_path}")
    print(f"  Passed {envelope['passed']}/{envelope['case_count']}")

    if config.langfuse_enabled:
        flush()
        shutdown()
        print("  Langfuse events flushed ✓")
        print(
            f"  Filter in Langfuse by tag `run:{run_name}` "
            f"or environment `{config.langfuse_environment}`"
        )
    else:
        print("  Dry-run: skipped Langfuse (add keys later, then drop --dry-run)")

    if envelope["failed"]:
        sys.exit(1)


if __name__ == "__main__":
    main()
