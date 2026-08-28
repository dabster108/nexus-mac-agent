"""macOS detection and safe subprocess execution.

Every command this server runs is a fixed argv list against a known absolute
path. Nothing is ever passed through a shell, and user input never becomes a
command or an argument to one — it only ever *selects* from a set this server
built itself.
"""

from __future__ import annotations

import subprocess
import sys
from dataclasses import dataclass
from threading import Thread
from typing import BinaryIO

MACOS_REQUIRED_MESSAGE = "NEXUS Mac MCP requires macOS."

DEFAULT_TIMEOUT = 5.0
MAX_OUTPUT_BYTES = 100_000


def is_macos() -> bool:
    return sys.platform == "darwin"


def require_macos() -> None:
    """Abort startup on anything that is not macOS."""
    if not is_macos():
        raise SystemExit(MACOS_REQUIRED_MESSAGE)


class CommandError(RuntimeError):
    """A helper command failed. Carries a message safe to show the agent."""


@dataclass(frozen=True, slots=True)
class CommandResult:
    stdout: str
    stderr: str
    truncated: bool = False


def _drain_limited(
    stream: BinaryIO, limit: int, output: list[bytes], truncated: list[bool]
) -> None:
    """Drain a pipe completely while retaining only a bounded prefix."""
    retained = 0
    while chunk := stream.read(8192):
        if retained < limit:
            keep = chunk[: limit - retained]
            output.append(keep)
            retained += len(keep)
        if len(chunk) > max(0, limit - retained):
            truncated[0] = True


def run(argv: list[str], timeout: float = DEFAULT_TIMEOUT) -> CommandResult:
    """Run a fixed command with no shell involved.

    ``argv[0]`` must be an absolute path to a system binary. Raises
    :class:`CommandError` with a short message rather than leaking a traceback.
    """
    if not argv or not argv[0].startswith("/"):
        raise CommandError("Refusing to run a command without an absolute path.")
    try:
        process = subprocess.Popen(  # noqa: S603 - fixed argv, never shell
            argv,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
    except FileNotFoundError as exc:
        raise CommandError(f"{argv[0]} is not available on this system.") from exc
    except OSError as exc:
        raise CommandError(f"Could not run {argv[0]}: {exc.strerror or exc}.") from exc

    stdout_chunks: list[bytes] = []
    stderr_chunks: list[bytes] = []
    stdout_truncated = [False]
    stderr_truncated = [False]
    readers = [
        Thread(
            target=_drain_limited,
            args=(process.stdout, MAX_OUTPUT_BYTES, stdout_chunks, stdout_truncated),
            daemon=True,
        ),
        Thread(
            target=_drain_limited,
            args=(process.stderr, MAX_OUTPUT_BYTES, stderr_chunks, stderr_truncated),
            daemon=True,
        ),
    ]
    for reader in readers:
        reader.start()
    try:
        process.wait(timeout=timeout)
    except subprocess.TimeoutExpired as exc:
        process.kill()
        process.wait()
        for reader in readers:
            reader.join()
        raise CommandError(f"{argv[0]} did not respond in time.") from exc
    for reader in readers:
        reader.join()

    stdout = b"".join(stdout_chunks).decode("utf-8", errors="replace")
    stderr = b"".join(stderr_chunks).decode("utf-8", errors="replace")
    if process.returncode != 0:
        detail = stderr.strip().splitlines()
        reason = detail[0] if detail else f"exit code {process.returncode}"
        raise CommandError(f"{argv[0]} failed: {reason}")
    return CommandResult(
        stdout=stdout,
        stderr=stderr,
        truncated=stdout_truncated[0] or stderr_truncated[0],
    )
