"""Running a verification plan. The only part of this package that does I/O.

Three properties hold here by construction rather than by care:

* **No model.** Nothing in this module's imports can reach a provider. The
  outcome is decided by :mod:`app.verification.rules`, which is pure.
* **SAFE only.** Every call goes through :meth:`_call_safe`, which re-checks
  the live registry's classification. A verifier that could reach a CONFIRM
  tool would be a machine-changing action nobody approved, which is precisely
  what this phase must not introduce.
* **Bounded.** Steps, tool calls and wall-clock are all capped, and exceeding
  any of them yields UNKNOWN rather than a retry. Verification is meant to be
  cheaper than the action it checks.
"""

from __future__ import annotations

import asyncio
import time
from typing import Any

from app.core.logging import get_logger
from app.tools.permissions import PermissionLevel
from app.tools.registry import ToolRegistry
from app.verification import rules
from app.verification.models import (
    MAX_VERIFICATION_RUNTIME_SECONDS,
    MAX_VERIFICATION_STEPS,
    MAX_VERIFICATION_TOOL_CALLS,
    Evidence,
    Outcome,
    Verification,
    unknown,
)
from app.verification.planner import Plan, Strategy, build

logger = get_logger(__name__)

#: How long to wait before re-checking a service that has not answered yet.
#: A development server binds its port a second or two after the process
#: exists, so checking immediately reports "not answering" for every healthy
#: start. One short re-check turns a permanent PARTIAL into an honest SUCCESS
#: without ever waiting on something that is genuinely dead.
SETTLE_SECONDS = 1.5

#: Re-checks allowed. One: past that we are polling, and a service that needs
#: longer than this is better reported as PARTIAL than waited on.
MAX_SETTLE_RETRIES = 1


def _self_reported_failure(result: dict[str, Any]) -> str | None:
    """The tool's own words, when its result says the action did not happen.

    Deliberately narrow: only an explicit ``success: false``. An absent key is
    not read as failure, because plenty of tools simply do not report one and
    guessing is what this layer exists to avoid.
    """
    if not isinstance(result, dict) or result.get("success") is not False:
        return None
    reason = result.get("error") or result.get("message") or ""
    text = str(reason).strip()
    return text or "the tool reported that it did not succeed"


class Verifier:
    """Checks whether a completed action achieved what was asked."""

    def __init__(
        self,
        registry: ToolRegistry,
        *,
        max_steps: int = MAX_VERIFICATION_STEPS,
        max_tool_calls: int = MAX_VERIFICATION_TOOL_CALLS,
        max_runtime_seconds: float = MAX_VERIFICATION_RUNTIME_SECONDS,
    ) -> None:
        self._registry = registry
        self._max_steps = max_steps
        self._max_tool_calls = max_tool_calls
        self._max_runtime = max_runtime_seconds
        self._calls = 0

    # --- the SAFE-only door ------------------------------------------------

    async def _call_safe(self, tool: str, arguments: dict) -> dict | None:
        definition = self._registry.get(tool)
        if definition is None:
            return None
        if definition.permission is not PermissionLevel.SAFE:
            # Defensive: verification must never change anything.
            logger.error("Verifier refused to call non-SAFE tool '%s'", tool)
            return None
        if self._calls >= self._max_tool_calls:
            logger.warning("Verification tool-call budget spent; stopping")
            return None
        self._calls += 1
        try:
            result = await self._registry.call(tool, arguments)
        except Exception:  # noqa: BLE001 - a failed check is UNKNOWN, not an error
            logger.warning("Verification: '%s' failed", tool, exc_info=True)
            return None
        if result.is_error or not isinstance(result.structured, dict):
            return None
        return result.structured

    # --- the entry point ---------------------------------------------------

    async def verify(
        self, *, tool: str, result: dict[str, Any], arguments: dict[str, Any]
    ) -> Verification:
        """Check one completed action. Never raises."""
        started = time.perf_counter()
        self._calls = 0

        # The action's own result may already settle it. A tool that reports
        # `success: false` did not do the thing, and saying "could not be
        # verified" there understates what we plainly know — the same failure
        # of honesty as claiming SUCCESS from a tool that merely returned.
        # No tool call is needed: the refusal *is* the observation.
        refusal = _self_reported_failure(result)
        if refusal is not None:
            return Verification(
                tool=tool,
                outcome=Outcome.FAILED,
                summary="The action did not go through.",
                evidence=(Evidence.observed(tool, refusal),),
                duration_ms=(time.perf_counter() - started) * 1000,
            )

        plan = build(
            tool=tool, registry=self._registry, result=result, arguments=arguments
        )
        if plan.strategy is Strategy.NONE:
            return unknown(tool, plan.reason or "there is nothing to check")

        try:
            async with asyncio.timeout(self._max_runtime):
                verification = await self._run(plan, result, arguments)
        except TimeoutError:
            logger.warning("Verification of '%s' timed out", tool)
            return unknown(tool, "verification took too long and was stopped")

        return Verification(
            tool=verification.tool,
            outcome=verification.outcome,
            evidence=verification.evidence,
            summary=verification.summary,
            unknowns=verification.unknowns,
            duration_ms=(time.perf_counter() - started) * 1000,
            tool_calls=self._calls,
        )

    async def _settle(
        self,
        plan: Plan,
        status: dict[str, Any] | None,
        service: dict[str, Any] | None,
    ) -> dict[str, Any] | None:
        """Give a live process one brief chance to start answering.

        Only when the process is demonstrably alive and the port simply has not
        opened yet — a dead process is never waited on, and there is exactly one
        retry, so this cannot become a poll loop.
        """
        if service is None or service.get("reachable"):
            return service
        if not status or str(status.get("status")) not in ("RUNNING", "STARTING"):
            return service

        check = next(
            (c for c in plan.checks if c.tool == "check_local_service"), None
        )
        if check is None:
            return service

        for _ in range(MAX_SETTLE_RETRIES):
            await asyncio.sleep(SETTLE_SECONDS)
            retried = await self._call_safe(check.tool, check.arguments)
            if retried is None:
                return service
            service = retried
            if service.get("reachable"):
                break
        return service

    async def _run(
        self, plan: Plan, result: dict[str, Any], arguments: dict[str, Any]
    ) -> Verification:
        if plan.strategy is Strategy.EXIT_CODE:
            return rules.exit_code(plan.tool, result)

        if plan.is_empty:
            return unknown(plan.tool, plan.reason or "there was nothing to check")

        # The plan is fixed before anything runs and cannot grow, so the step
        # bound is a property of the plan rather than of the loop.
        gathered: dict[str, dict[str, Any] | None] = {}
        for check in plan.checks[: self._max_steps]:
            gathered[check.tool] = await self._call_safe(check.tool, check.arguments)

        if plan.strategy is Strategy.PROCESS_RUNNING:
            status = gathered.get("process_status")
            service = gathered.get("check_local_service")
            service = await self._settle(plan, status, service)
            return rules.process_running(plan.tool, status, service)
        if plan.strategy is Strategy.PROCESS_STOPPED:
            return rules.process_stopped(plan.tool, gathered.get("process_status"))
        if plan.strategy is Strategy.LOCAL_SERVICE:
            return rules.local_service(plan.tool, gathered.get("check_local_service"))
        if plan.strategy is Strategy.APPLICATION:
            return rules.application(
                plan.tool,
                str(arguments.get("application") or ""),
                gathered.get("running_processes"),
            )

        return unknown(plan.tool, "no rule for that strategy")


#: Outcomes that mean the user's goal was *not* met. Used by the callers that
#: turn a verification into an observation, a suggestion or a mission branch.
NEGATIVE_OUTCOMES = frozenset({Outcome.FAILED})


__all__ = ["NEGATIVE_OUTCOMES", "Verifier"]
