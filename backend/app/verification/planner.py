"""Deciding *how* to check an action, from the tool's own declaration.

A tool says what verifying it looks like through MCP metadata:

    {"nexus": {"verification": {"type": "process", "process_id_from": "result"}}}

The backend reads that from the live registry rather than keeping a table of
tool names, so a new MCP server can arrive with verifiable tools and nothing
here changes. A tool that declares nothing is not guessed at — the runtime
returns UNKNOWN, which is the honest answer and also the one that cannot be
wrong.

The plan itself is a list of SAFE tool calls. It is built before anything runs
and cannot grow while running, which is what makes the loop limits real rather
than aspirational.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from app.tools.registry import ToolDefinition, ToolRegistry


class Strategy(StrEnum):
    PROCESS_RUNNING = "process"
    """The action should have left a process alive."""

    PROCESS_STOPPED = "process_stopped"
    """The action should have stopped one."""

    LOCAL_SERVICE = "local_service"
    """The action should have left something answering on a URL."""

    EXIT_CODE = "exit_code"
    """The action's own result carries the answer; nothing else is needed."""

    APPLICATION = "application"
    """An application was launched; only its presence can be checked."""

    NONE = "none"
    """Declared unverifiable. Distinct from "undeclared" — this is a tool
    saying there is nothing to check, not a tool that forgot to say."""


@dataclass(frozen=True, slots=True)
class Check:
    """One SAFE call the verifier will make."""

    tool: str
    arguments: dict[str, Any]
    #: What this check is establishing, for the evidence line.
    purpose: str


@dataclass(frozen=True, slots=True)
class Plan:
    """Everything the verifier is allowed to do for one action."""

    tool: str
    strategy: Strategy
    checks: tuple[Check, ...] = ()
    reason: str = ""

    @property
    def is_empty(self) -> bool:
        return not self.checks and self.strategy is not Strategy.EXIT_CODE


def contract_for(definition: ToolDefinition | None) -> dict[str, Any] | None:
    """The tool's declared verification contract, if it has one."""
    if definition is None:
        return None
    meta = getattr(definition, "meta", None) or {}
    if not isinstance(meta, dict):
        return None
    contract = meta.get("verification")
    return contract if isinstance(contract, dict) else None


def _pick(source: str, result: dict[str, Any], arguments: dict[str, Any], key: str) -> Any:
    """Resolve `*_from: result|arguments` against the actual call."""
    if source == "arguments":
        return arguments.get(key)
    return result.get(key)


def build(
    *,
    tool: str,
    registry: ToolRegistry,
    result: dict[str, Any],
    arguments: dict[str, Any],
) -> Plan:
    """The plan for verifying one completed action."""
    definition = registry.get(tool)
    contract = contract_for(definition)
    if contract is None:
        return Plan(
            tool=tool,
            strategy=Strategy.NONE,
            reason=f"'{tool}' does not declare how it can be verified",
        )

    declared = str(contract.get("type") or "").strip().lower()
    try:
        strategy = Strategy(declared)
    except ValueError:
        return Plan(
            tool=tool,
            strategy=Strategy.NONE,
            reason=f"'{declared}' is not a verification strategy this backend knows",
        )

    if strategy is Strategy.EXIT_CODE:
        # The action's own result is the evidence; running anything else to
        # "confirm" a test suite would be doing the work twice.
        return Plan(tool=tool, strategy=strategy)

    if strategy in (Strategy.PROCESS_RUNNING, Strategy.PROCESS_STOPPED):
        process_id = _pick(
            str(contract.get("process_id_from") or "result"),
            result,
            arguments,
            "process_id",
        )
        if not process_id:
            return Plan(
                tool=tool, strategy=strategy, reason="no process id was returned"
            )
        checks = [
            Check(
                tool="process_status",
                arguments={"process_id": str(process_id)},
                purpose="whether the process is still running",
            )
        ]
        # A URL only matters for something that should now be *up*.
        if strategy is Strategy.PROCESS_RUNNING:
            url = _pick(
                str(contract.get("url_from") or "result"), result, arguments, "url"
            )
            if url and registry.get("check_local_service") is not None:
                checks.append(
                    Check(
                        tool="check_local_service",
                        arguments={"url": str(url)},
                        purpose="whether it is answering",
                    )
                )
        return Plan(tool=tool, strategy=strategy, checks=tuple(checks))

    if strategy is Strategy.LOCAL_SERVICE:
        url = _pick(str(contract.get("url_from") or "result"), result, arguments, "url")
        if not url:
            return Plan(tool=tool, strategy=strategy, reason="no URL was returned")
        return Plan(
            tool=tool,
            strategy=strategy,
            checks=(
                Check(
                    tool="check_local_service",
                    arguments={"url": str(url)},
                    purpose="whether it is answering",
                ),
            ),
        )

    if strategy is Strategy.APPLICATION:
        name = _pick(
            str(contract.get("name_from") or "arguments"), result, arguments, "application"
        )
        if not name or registry.get("running_processes") is None:
            return Plan(
                tool=tool,
                strategy=strategy,
                reason="the application's process cannot be looked up",
            )
        return Plan(
            tool=tool,
            strategy=strategy,
            checks=(
                Check(
                    tool="running_processes",
                    arguments={"limit": 200},
                    purpose="whether the application is running",
                ),
            ),
        )

    return Plan(tool=tool, strategy=Strategy.NONE, reason="nothing to check")


__all__ = ["Check", "Plan", "Strategy", "build", "contract_for"]
