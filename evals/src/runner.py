"""Eval runner — drives the NEXUS backend and traces results to Langfuse.

The runner is an *external* client. It talks to the backend over HTTP (the
same way the frontend does) and records everything in Langfuse as traces with
generations and spans. The backend itself is not modified.
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from typing import Any

import httpx

from src.client import get_langfuse
from src.config import EvalConfig
from src.dataset import EvalCase
from src.scorers import score_result


@dataclass(slots=True)
class EvalResult:
    """The outcome of running one eval case."""

    case_id: str
    task_id: str | None = None
    status: str = "pending"
    response: str = ""
    tools_called: list[str] = field(default_factory=list)
    outcome: str = ""
    trace: dict[str, Any] = field(default_factory=dict)
    scores: dict[str, float] = field(default_factory=dict)
    latency_ms: float = 0.0
    error: str | None = None


async def run_case(
    case: EvalCase,
    config: EvalConfig,
    *,
    timeout: float = 90.0,
    auto_approve: bool = False,
) -> EvalResult:
    """Run a single eval case against the live NEXUS backend.

    1. POST /api/chat with the case input
    2. Poll /api/tasks/{id} until completed or failed
    3. Fetch the trace
    4. Score the result
    5. Push trace + scores to Langfuse
    """
    result = EvalResult(case_id=case.id)
    langfuse = get_langfuse(config)
    base = config.nexus_api_url.rstrip("/")

    lf_trace = langfuse.trace(
        name=f"eval::{case.id}",
        metadata={"dataset": "core", "tags": case.tags, **case.metadata},
        tags=["eval", *case.tags],
    )

    t0 = time.monotonic()

    async with httpx.AsyncClient(base_url=base, timeout=timeout) as http:
        # --- 1. Send the message ----------------------------------------
        try:
            chat_resp = await http.post(
                "/api/chat",
                json={"message": case.input},
            )
            chat_resp.raise_for_status()
            task_id = chat_resp.json().get("task_id")
            result.task_id = task_id
        except Exception as exc:
            result.error = f"chat failed: {exc}"
            result.status = "error"
            return result

        lf_trace.update(session_id=task_id)

        # --- 2. Poll until done ----------------------------------------
        span = lf_trace.span(name="poll_task", input={"task_id": task_id})
        deadline = time.monotonic() + timeout
        task_data: dict[str, Any] = {}

        while time.monotonic() < deadline:
            try:
                poll = await http.get(f"/api/tasks/{task_id}")
                poll.raise_for_status()
                task_data = poll.json()
            except Exception:
                await asyncio.sleep(1.0)
                continue

            status = task_data.get("status", "")
            result.status = status

            # Auto-approve CONFIRM tools if requested
            if auto_approve and status == "waiting":
                pending = await http.get("/api/permissions")
                for req in pending.json().get("requests", []):
                    if req.get("task_id") == task_id:
                        await http.post(
                            f"/api/permissions/{req['id']}/approve"
                        )

            if status in ("completed", "error", "timeout"):
                break

            await asyncio.sleep(1.0)

        span.end(output={"final_status": result.status})
        result.latency_ms = (time.monotonic() - t0) * 1000

        # --- 3. Collect the response and tools --------------------------
        result.response = task_data.get("response", "")
        events = task_data.get("events", [])
        result.tools_called = [
            e.get("tool") or e.get("data", {}).get("tool", "")
            for e in events
            if e.get("type") == "tool_started"
        ]
        result.outcome = task_data.get("outcome", {}).get("verdict", "")

        # Record the generation in Langfuse
        lf_trace.generation(
            name="agent_response",
            input=case.input,
            output=result.response,
            metadata={
                "tools_called": result.tools_called,
                "outcome": result.outcome,
            },
        )

        # --- 4. Fetch trace ---------------------------------------------
        try:
            trace_resp = await http.get(f"/api/tasks/{task_id}/trace")
            if trace_resp.status_code == 200:
                result.trace = trace_resp.json()
        except Exception:
            pass

        # --- 5. Score ---------------------------------------------------
        result.scores = score_result(case, result)

        for score_name, score_value in result.scores.items():
            lf_trace.score(name=score_name, value=score_value)

    return result


async def run_dataset(
    cases: list[EvalCase],
    config: EvalConfig,
    *,
    auto_approve: bool = False,
    concurrency: int = 1,
) -> list[EvalResult]:
    """Run all cases in a dataset, respecting concurrency limit."""
    sem = asyncio.Semaphore(concurrency)

    async def _bounded(case: EvalCase) -> EvalResult:
        async with sem:
            return await run_case(case, config, auto_approve=auto_approve)

    results = await asyncio.gather(*[_bounded(c) for c in cases])
    return list(results)
