"""Harness orchestration (mocked target)."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from src.config import EvalConfig
from src.harness import EvalHarness, format_case_line
from src.runner import EvalResult
from src.schema import RUN_SCHEMA


def _config() -> EvalConfig:
    return EvalConfig(
        langfuse_secret_key=None,
        langfuse_public_key=None,
        langfuse_host="https://us.cloud.langfuse.com",
        langfuse_environment="dev",
        nexus_api_url="http://127.0.0.1:8000",
        dry_run=True,
    )


@pytest.mark.asyncio
async def test_harness_writes_envelope(tmp_path: Path) -> None:
    fake = [
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
            latency_ms=100,
        )
    ]
    logs: list[str] = []

    with (
        patch("src.harness.check_backend", new=AsyncMock(return_value="ok")),
        patch("src.harness.run_dataset", new=AsyncMock(return_value=fake)),
        patch("src.harness.load_eval_dataset") as load,
    ):
        from src.dataset import EvalCase, EvalDataset

        load.return_value = EvalDataset(
            name="smoke",
            version="1",
            cases=(EvalCase(id="battery_check", input="battery?"),),
            path=tmp_path / "smoke.yaml",
        )
        harness = EvalHarness(
            config=_config(),
            dataset_name="smoke",
            run_name="unit-1",
            skip_health=False,
            skip_sync=True,
            results_dir=tmp_path,
            log=logs.append,
        )
        run = await harness.run()

    assert run.envelope["schema"] == RUN_SCHEMA
    assert run.envelope["passed"] == 1
    assert run.artifacts.envelope_path.exists()
    assert run.artifacts.markdown_path.exists()
    assert run.artifacts.alias_path is not None
    assert any("Running 1 case" in line for line in logs)


def test_format_case_line() -> None:
    line = format_case_line(
        EvalResult(
            case_id="x",
            status="completed",
            scores={"tool_selection": 1.0, "outcome": 1.0, "keywords": 1.0,
                     "completion": 1.0, "safety": 1.0, "latency": 0.1},
        )
    )
    assert "✓" in line
    assert "x" in line
