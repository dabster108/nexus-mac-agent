"""CONFIRM tool: run an approved developer command.

Execution only. By the time anything here spawns a process, the command has
already been parsed, matched against an explicit profile and cleared by the
blocklist in :mod:`nexus_mac_mcp.core.commands`, and the working directory has
been checked by :mod:`nexus_mac_mcp.core.filesystem`.

How the process is run:

* **argv, never a shell.** ``subprocess.Popen`` with a list. No ``shell=True``,
  no ``os.system``, no ``/bin/sh -c``. The tokens the model produced can only
  ever be arguments, never syntax.
* **Its own process group** (``start_new_session``), so a timeout can end the
  whole tree rather than orphaning children — which matters the moment a
  command spawns workers.
* **Bounded output.** Reader threads drain both pipes so the child never blocks
  on a full buffer, but keep only the first N bytes. A runaway process cannot
  exhaust memory or flood the model's context.
* **Bounded time**, with SIGTERM before SIGKILL.
"""

from __future__ import annotations

import os
import signal
import subprocess
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import IO, Any

from nexus_mac_mcp.core.commands import (
    CommandPolicyError,
    ValidatedCommand,
    validate_command_text,
)
from nexus_mac_mcp.core.environment import build_environment, resolve_executable
from nexus_mac_mcp.core.filesystem import (
    FilesystemPolicy,
    PathError,
    policy_or_default,
    resolve_safe_path,
)

DEFAULT_MAX_OUTPUT_BYTES = 100_000
DEFAULT_TIMEOUT_SECONDS = 120.0
#: How long a terminated process gets to exit before it is killed outright.
GRACE_SECONDS = 5.0

LONG_RUNNING_MESSAGE = (
    "This command starts a server that would never finish on its own. "
    "Use start_process instead, which supervises it in the background."
)


def _limits() -> tuple[int, float]:
    def _number(name: str, default: float) -> float:
        raw = os.getenv(name, "").strip()
        try:
            value = float(raw) if raw else default
        except ValueError:
            return default
        return value if value > 0 else default

    return (
        int(_number("NEXUS_MAC_MAX_OUTPUT_BYTES", DEFAULT_MAX_OUTPUT_BYTES)),
        _number("NEXUS_MAC_COMMAND_TIMEOUT", DEFAULT_TIMEOUT_SECONDS),
    )


@dataclass(slots=True)
class _Drain:
    """Reads a pipe to the end, keeping at most ``limit`` bytes."""

    stream: IO[bytes]
    limit: int
    chunks: list[bytes]
    total: int = 0

    def run(self) -> None:
        try:
            while True:
                # read1: return what is available rather than blocking for a
                # full buffer, so a slow producer cannot stall the drain.
                chunk = self.stream.read1(8192)
                if not chunk:
                    return
                if self.total < self.limit:
                    self.chunks.append(chunk[: self.limit - self.total])
                self.total += len(chunk)
        except (OSError, ValueError):  # pipe closed under us
            return

    @property
    def text(self) -> str:
        return b"".join(self.chunks).decode("utf-8", errors="replace")

    @property
    def truncated(self) -> bool:
        return self.total > self.limit


def _failure(error: str, status: str = "rejected", **extra: Any) -> dict[str, Any]:
    return {"success": False, "status": status, "error": error, **extra}


def _terminate(process: subprocess.Popen[bytes]) -> None:
    """End the whole process group: SIGTERM, then SIGKILL if it lingers."""
    try:
        group = os.getpgid(process.pid)
    except (ProcessLookupError, OSError):
        return

    for sig in (signal.SIGTERM, signal.SIGKILL):
        try:
            os.killpg(group, sig)
        except (ProcessLookupError, PermissionError, OSError):
            return
        try:
            process.wait(timeout=GRACE_SECONDS)
            return
        except subprocess.TimeoutExpired:
            continue


def _execute(
    validated: ValidatedCommand,
    directory: Path,
    max_output: int,
    timeout: float,
) -> dict[str, Any]:
    executable = resolve_executable(validated.request.executable)
    if executable is None:
        return _failure(
            f"'{validated.request.executable}' is not installed on this Mac.",
            status="unavailable",
        )

    argv = [executable, *validated.request.args]
    started = time.perf_counter()
    try:
        process = subprocess.Popen(  # noqa: S603 - argv list, never a shell
            argv,
            cwd=str(directory),
            env=build_environment(),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            stdin=subprocess.DEVNULL,
            start_new_session=True,  # its own process group, so children die too
        )
    except (OSError, ValueError) as exc:
        return _failure(f"That command could not be started: {exc}", status="failed")

    assert process.stdout is not None and process.stderr is not None
    out = _Drain(process.stdout, max_output, [])
    err = _Drain(process.stderr, max_output, [])
    readers = [threading.Thread(target=drain.run, daemon=True) for drain in (out, err)]
    for reader in readers:
        reader.start()

    timed_out = False
    try:
        process.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        timed_out = True
        _terminate(process)

    for reader in readers:
        reader.join(timeout=GRACE_SECONDS)
    for pipe in (process.stdout, process.stderr):
        try:
            pipe.close()
        except OSError:  # pragma: no cover - already closed
            pass

    duration = round(time.perf_counter() - started, 3)
    result: dict[str, Any] = {
        "command": validated.display,
        "working_directory": str(directory),
        "stdout": out.text,
        "stderr": err.text,
        "truncated": out.truncated or err.truncated,
        "duration_seconds": duration,
    }

    if timed_out:
        return {
            **result,
            "success": False,
            "status": "timeout",
            "exit_code": None,
            "error": f"The command did not finish within {timeout:g} seconds.",
        }

    exit_code = process.returncode
    return {
        **result,
        "success": exit_code == 0,
        "status": "completed" if exit_code == 0 else "failed",
        "exit_code": exit_code,
    }


def run_command(
    command: str,
    working_directory: str,
    policy: FilesystemPolicy | None = None,
) -> dict[str, Any]:
    """Validate a developer command and, if it is allowed, run it."""
    policy = policy_or_default(policy)

    try:
        validated = validate_command_text(command)
    except CommandPolicyError as exc:
        return _failure(str(exc))

    try:
        directory = resolve_safe_path(
            working_directory, policy=policy, require_directory=True
        )
    except PathError as exc:
        return _failure(str(exc))

    if validated.long_running:
        # Detected, not run: supervising it is start_process's job.
        return _failure(
            LONG_RUNNING_MESSAGE,
            status="unsupported",
            command=validated.display,
            working_directory=str(directory),
        )

    max_output, timeout = _limits()
    return _execute(validated, directory, max_output, timeout)
