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

MACOS_REQUIRED_MESSAGE = "NEXUS Mac MCP requires macOS."

DEFAULT_TIMEOUT = 5.0


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


def run(argv: list[str], timeout: float = DEFAULT_TIMEOUT) -> CommandResult:
    """Run a fixed command with no shell involved.

    ``argv[0]`` must be an absolute path to a system binary. Raises
    :class:`CommandError` with a short message rather than leaking a traceback.
    """
    if not argv or not argv[0].startswith("/"):
        raise CommandError("Refusing to run a command without an absolute path.")
    try:
        completed = subprocess.run(  # noqa: S603 - fixed argv, never shell
            argv,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except FileNotFoundError as exc:
        raise CommandError(f"{argv[0]} is not available on this system.") from exc
    except subprocess.TimeoutExpired as exc:
        raise CommandError(f"{argv[0]} did not respond in time.") from exc
    except OSError as exc:
        raise CommandError(f"Could not run {argv[0]}: {exc.strerror or exc}.") from exc

    if completed.returncode != 0:
        detail = completed.stderr.strip().splitlines()
        reason = detail[0] if detail else f"exit code {completed.returncode}"
        raise CommandError(f"{argv[0]} failed: {reason}")
    return CommandResult(stdout=completed.stdout, stderr=completed.stderr)
