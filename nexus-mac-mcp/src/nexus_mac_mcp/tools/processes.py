"""Tools for managing development processes.

The three read-only tools report on processes NEXUS itself started — never on
anything else running on the Mac. Starting and stopping are CONFIRM-level and
gated by the backend's approval broker like any other tool that changes
something.
"""

from __future__ import annotations

from typing import Any

from nexus_mac_mcp.core.commands import CommandPolicyError
from nexus_mac_mcp.core.filesystem import (
    FilesystemPolicy,
    PathError,
    policy_or_default,
    resolve_safe_path,
)
from nexus_mac_mcp.core.process_manager import (
    DEFAULT_LOG_LINES,
    MAX_LOG_LINES,
    ProcessError,
    ProcessManager,
    get_process_manager,
)
from nexus_mac_mcp.core.process_policy import validate_process_command


def _failure(error: str) -> dict[str, Any]:
    return {"success": False, "error": error}


def _manager_or_default(manager: ProcessManager | None) -> ProcessManager:
    return manager if manager is not None else get_process_manager()


def start_process(
    command: str,
    working_directory: str,
    policy: FilesystemPolicy | None = None,
    manager: ProcessManager | None = None,
) -> dict[str, Any]:
    """Start a development server and leave it running under supervision."""
    policy = policy_or_default(policy)
    manager = _manager_or_default(manager)

    try:
        # The ordinary command policy first, then the background question.
        validated = validate_process_command(command)
    except CommandPolicyError as exc:
        return _failure(str(exc))

    try:
        directory = resolve_safe_path(
            working_directory, policy=policy, require_directory=True
        )
    except PathError as exc:
        return _failure(str(exc))

    try:
        record = manager.start(
            command=validated.display,
            argv=[validated.command.request.executable, *validated.command.request.args],
            working_directory=directory,
            host=validated.host,
            port=validated.port,
            label=validated.profile.label,
        )
    except ProcessError as exc:
        return _failure(str(exc))

    return {"success": True, **record.summary()}


def list_processes(manager: ProcessManager | None = None) -> dict[str, Any]:
    """Every process NEXUS is managing. Not the machine's process table."""
    manager = _manager_or_default(manager)
    processes = [record.summary() for record in manager.list()]
    return {"success": True, "processes": processes, "count": len(processes)}


def process_status(
    process_id: str, manager: ProcessManager | None = None
) -> dict[str, Any]:
    """The current state of one managed process."""
    manager = _manager_or_default(manager)
    try:
        return {"success": True, **manager.get(process_id).summary()}
    except ProcessError as exc:
        return _failure(str(exc))


def process_logs(
    process_id: str,
    lines: int = DEFAULT_LOG_LINES,
    manager: ProcessManager | None = None,
) -> dict[str, Any]:
    """Recent output from a managed process."""
    manager = _manager_or_default(manager)
    if lines < 1:
        return _failure("lines must be at least 1.")
    lines = min(lines, MAX_LOG_LINES)
    try:
        record = manager.get(process_id)
    except ProcessError as exc:
        return _failure(str(exc))
    return {"success": True, **record.logs(lines)}


def stop_process(
    process_id: str, manager: ProcessManager | None = None
) -> dict[str, Any]:
    """Stop a managed process, and everything it spawned."""
    manager = _manager_or_default(manager)
    try:
        record = manager.stop(process_id)
    except ProcessError as exc:
        return _failure(str(exc))
    return {"success": True, **record.summary()}
