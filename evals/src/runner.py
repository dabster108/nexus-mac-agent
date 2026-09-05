"""Eval runner — drives the NEXUS backend and traces results to Langfuse v4.

The runner is an *external* client. It talks to the backend over HTTP (the
same way the frontend does) and records everything in Langfuse as observations
with scores. The backend itself is not modified.
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from typing import Any

import httpx
from langfuse import propagate_attributes

from src.client import get_langfuse
from src.config import EvalConfig
from src.dataset import EvalCase
from src.scorers import score_result

#: Task statuses that mean the run is finished (matches backend TaskStatus).
_TERMINAL = frozenset({"completed", "error", "cancelled"})


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
    langfuse_trace_url: str | None = None


def _tools_from_events(events: list[dict[str, Any]]) -> list[str]:
    """Unique tool names in call order from ``tool_started`` events."""
    seen: set[str] = set()
    ordered: list[str] = []
    for event in events:
        if event.get("type") != "tool_started":
            continue
        tool = event.get("tool") or (event.get("data") or {}).get("tool")
        if tool and tool not in seen:
            seen.add(tool)
            ordered.append(tool)
    return ordered


def _outcome_from_trace(trace: dict[str, Any], events: list[dict[str, Any]]) -> str:
    """Prefer the projected trace outcome; fall back to verification events."""
    outcome = trace.get("outcome")
    if outcome:
        return str(outcome)
    for event in reversed(events):
        if event.get("type") != "verification_completed":
            continue
        found = (event.get("data") or {}).get("outcome")
        if found:
            return str(found)
    return ""


async def _approve_pending(http: httpx.AsyncClient, task_id: str) -> None:
    """Approve every pending CONFIRM request for this task."""
    try:
        pending = await http.get("/api/permissions/pending")
        pending.raise_for_status()
    except Exception:
        return
    for req in pending.json().get("requests", []):
        if req.get("task_id") != task_id:
            continue
        request_id = req.get("request_id")
        if not request_id:
            continue
        try:
            await http.post(f"/api/permissions/{request_id}/approve")
        except Exception:
            continue


async def run_case(
    case: EvalCase,
    config: EvalConfig,
    *,
    dataset_name: str = "core",
    timeout: float = 90.0,
    auto_approve: bool = False,
) -> EvalResult:
    """Run a single eval case against the live NEXUS backend.

    1. POST /api/chat with the case input
    2. Poll /api/tasks/{id} until completed / error / cancelled
    3. Fetch /api/tasks/{id}/trace when available
    4. Score the result
    5. Push observation + scores to Langfuse
    """
    result = EvalResult(case_id=case.id)
    langfuse = get_langfuse(config)
    base = config.nexus_api_url.rstrip("/")
    t0 = time.monotonic()

    with langfuse.start_as_current_observation(
        as_type="span",
        name=f"eval::{case.id}",
        input={"message": case.input},
        metadata={
            "dataset": dataset_name,
            "case_id": case.id,
            "expected_tools": case.expected_tools,
            "expected_outcome": case.expected_outcome,
            **case.metadata,
        },
    ) as root:
        with propagate_attributes(
            tags=["eval", *case.tags],
            trace_name=f"eval::{case.id}",
            metadata={"dataset": dataset_name, "case_id": case.id},
        ):
            async with httpx.AsyncClient(base_url=base, timeout=timeout) as http:
                # --- 1. Send the message --------------------------------
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
                    result.latency_ms = (time.monotonic() - t0) * 1000
                    result.scores = score_result(case, result)
                    root.update(
                        output={"error": result.error, "status": result.status},
                        level="ERROR",
                        status_message=result.error,
                    )
                    for score_name, score_value in result.scores.items():
                        root.score_trace(
                            name=score_name,
                            value=score_value,
                            data_type="NUMERIC",
                        )
                    result.langfuse_trace_url = langfuse.get_trace_url()
                    return result

                with propagate_attributes(session_id=task_id):
                    # --- 2. Poll until done -----------------------------
                    with langfuse.start_as_current_observation(
                        as_type="span",
                        name="poll_task",
                        input={"task_id": task_id},
                    ) as poll_span:
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

                            status = str(task_data.get("status") or "")
                            result.status = status

                            if auto_approve and status == "permission_required":
                                await _approve_pending(http, task_id)

                            if status in _TERMINAL:
                                break

                            await asyncio.sleep(1.0)
                        else:
                            if result.status not in _TERMINAL:
                                result.status = "timeout"
                                result.error = result.error or "poll timed out"

                        poll_span.update(
                            output={
                                "final_status": result.status,
                                "task_id": task_id,
                            }
                        )

                    result.latency_ms = (time.monotonic() - t0) * 1000

                    # --- 3. Collect response, tools, outcome ------------
                    result.response = task_data.get("response") or ""
                    events = task_data.get("events") or []
                    result.tools_called = _tools_from_events(events)

                    try:
                        trace_resp = await http.get(f"/api/tasks/{task_id}/trace")
                        if trace_resp.status_code == 200:
                            result.trace = trace_resp.json()
                    except Exception:
                        pass

                    result.outcome = _outcome_from_trace(result.trace, events)

                    with langfuse.start_as_current_observation(
                        as_type="generation",
                        name="agent_response",
                        input=case.input,
                        metadata={
                            "tools_called": result.tools_called,
                            "outcome": result.outcome,
                            "task_status": result.status,
                        },
                    ) as generation:
                        generation.update(output=result.response or None)

                    # --- 4. Score ---------------------------------------
                    result.scores = score_result(case, result)

                    root.update(
                        output={
                            "status": result.status,
                            "response": result.response,
                            "tools_called": result.tools_called,
                            "outcome": result.outcome,
                            "latency_ms": result.latency_ms,
                            "scores": result.scores,
                            "error": result.error,
                        }
                    )

                    for score_name, score_value in result.scores.items():
                        root.score_trace(
                            name=score_name,
                            value=score_value,
                            data_type="NUMERIC",
                        )

                    result.langfuse_trace_url = langfuse.get_trace_url()

    return result


async def run_dataset(
    cases: list[EvalCase],
    config: EvalConfig,
    *,
    dataset_name: str = "core",
    auto_approve: bool = False,
    concurrency: int = 1,
) -> list[EvalResult]:
    """Run all cases in a dataset, respecting concurrency limit."""
    sem = asyncio.Semaphore(concurrency)

    async def _bounded(case: EvalCase) -> EvalResult:
        async with sem:
            return await run_case(
                case,
                config,
                dataset_name=dataset_name,
                auto_approve=auto_approve,
            )

    results = await asyncio.gather(*[_bounded(c) for c in cases])
    return list(results)
