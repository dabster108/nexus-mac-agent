"""Eval harness orchestration.

Layers (concept → module):

* **Cases** — versioned YAML (``dataset``)
* **Target** — live NEXUS HTTP API (``runner``)
* **Judges** — deterministic scorers (``scorers``)
* **Telemetry** — Langfuse observations + Datasets (``client`` / ``sync``)
* **Artifacts** — ``nexus-evals/v1`` envelope + markdown (``report``)

This module wires those layers into one run. The CLI (``__main__``) only
parses flags and prints progress.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from src.aggregates import aggregate_scores, case_average, passed_case
from src.config import EvalConfig
from src.dataset import EvalDataset, load_eval_dataset
from src.report import build_run_envelope, write_markdown_report
from src.runner import EvalResult, check_backend, run_dataset
from src.schema import RUN_SCHEMA
from src.sync import SyncResult, sync_dataset

LogFn = Callable[[str], None]


@dataclass(frozen=True)
class HarnessArtifacts:
    """Paths written for one completed harness run."""

    envelope_path: Path
    markdown_path: Path
    alias_path: Path | None


@dataclass
class HarnessRun:
    """Outcome of ``EvalHarness.run`` — machine-usable + printable."""

    envelope: dict[str, Any]
    results: list[EvalResult]
    aggregates: dict[str, float]
    artifacts: HarnessArtifacts
    dataset: EvalDataset
    synced: SyncResult | None = None


@dataclass
class EvalHarness:
    """Orchestrates one evaluation run against a configured target."""

    config: EvalConfig
    dataset_name: str
    run_name: str
    auto_approve: bool = False
    concurrency: int = 1
    skip_health: bool = False
    skip_sync: bool = False
    output: Path | None = None
    results_dir: Path = Path("results")
    log: LogFn = field(default=print, repr=False)

    async def run(self) -> HarnessRun:
        """Execute the full harness pipeline and persist artifacts."""
        concurrency = self.concurrency
        if self.auto_approve and concurrency > 1:
            self.log("  ⚠ --approve forces concurrency=1 (permission poll safety)")
            concurrency = 1

        if not self.skip_health:
            self.log(f"▸ Checking backend at {self.config.nexus_api_url} …")
            health = await check_backend(self.config)
            self.log(f"  ✓ {health}")

        synced: SyncResult | None = None
        if self.config.langfuse_enabled and not self.skip_sync:
            self.log(f"▸ Syncing '{self.dataset_name}' to Langfuse before run …")
            try:
                synced = sync_dataset(self.config, self.dataset_name)
                self.log(
                    f"  ✓ {synced.total} item(s) in `{synced.dataset}` "
                    f"(v{synced.version})"
                )
            except Exception as exc:
                self.log(f"  ⚠ Dataset sync failed ({exc}); continuing with local cases")

        dataset = load_eval_dataset(self.dataset_name)
        mode = (
            "dry-run (local scores only)"
            if self.config.dry_run
            else (
                f"Langfuse → {self.config.langfuse_host} "
                f"({self.config.langfuse_environment})"
            )
        )
        self.log(
            f"▸ Running {len(dataset.cases)} case(s) from "
            f"'{self.dataset_name}' v{dataset.version}"
        )
        self.log(f"  Backend: {self.config.nexus_api_url}")
        self.log(f"  Mode: {mode}")
        self.log(f"  Run: {self.run_name}")
        self.log(f"  Auto-approve: {self.auto_approve}")
        self.log("")

        started_at = datetime.now(UTC).isoformat()
        results = await run_dataset(
            list(dataset.cases),
            self.config,
            dataset_name=self.dataset_name,
            run_name=self.run_name,
            auto_approve=self.auto_approve,
            concurrency=concurrency,
        )
        aggregates = aggregate_scores(results)
        envelope = build_run_envelope(
            results,
            dataset=self.dataset_name,
            dataset_version=dataset.version,
            run_name=self.run_name,
            nexus_api_url=self.config.nexus_api_url,
            dry_run=self.config.dry_run,
            auto_approve=self.auto_approve,
            started_at=started_at,
        )
        if envelope.get("schema") != RUN_SCHEMA:
            raise RuntimeError(
                f"envelope schema mismatch: {envelope.get('schema')!r} != {RUN_SCHEMA!r}"
            )

        artifacts = self._write_artifacts(envelope, results, aggregates, dataset.version)
        return HarnessRun(
            envelope=envelope,
            results=results,
            aggregates=aggregates,
            artifacts=artifacts,
            dataset=dataset,
            synced=synced,
        )

    def _write_artifacts(
        self,
        envelope: dict[str, Any],
        results: list[EvalResult],
        aggregates: dict[str, float],
        dataset_version: str,
    ) -> HarnessArtifacts:
        out_path = self.output or (self.results_dir / f"{self.run_name}.json")
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json.dumps(envelope, indent=2))

        alias: Path | None = None
        if self.output is None:
            alias = self.results_dir / f"{self.dataset_name}.json"
            alias.write_text(json.dumps(envelope, indent=2))

        md_path = out_path.with_suffix(".md")
        write_markdown_report(
            results,
            dataset=self.dataset_name,
            path=md_path,
            dry_run=self.config.dry_run,
            nexus_api_url=self.config.nexus_api_url,
            run_name=self.run_name,
            dataset_version=dataset_version,
            aggregates=aggregates,
        )
        return HarnessArtifacts(
            envelope_path=out_path,
            markdown_path=md_path,
            alias_path=alias,
        )


def format_case_line(result: EvalResult) -> str:
    """One CLI progress line for a finished case."""
    mark = "✓" if passed_case(result) else "✗"
    tools_str = ", ".join(result.tools_called) if result.tools_called else "—"
    avg = case_average(result.scores)
    return (
        f"  {mark} {result.case_id:<28} {result.status:<20} "
        f"tools=[{tools_str}]  quality={avg:.2f}  {result.latency_ms:.0f}ms"
    )
