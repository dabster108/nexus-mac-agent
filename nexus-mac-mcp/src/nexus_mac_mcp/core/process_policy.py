"""Which commands may run as background processes.

This is a narrowing layer, not a second allowlist. Every request goes through
:mod:`nexus_mac_mcp.core.commands` first — the same policy `run_command` uses —
and only then is asked the extra question this module answers: *may this
particular command be left running in the background?*

The answer is yes for a short list of development servers and no for everything
else. A command being allowed to run does not make it allowed to run forever.
"""

from __future__ import annotations

from dataclasses import dataclass

from nexus_mac_mcp.core.commands import (
    CommandPolicyError,
    ValidatedCommand,
    option_value,
    validate_command_text,
)

DEFAULT_HOST = "127.0.0.1"
#: Used when uvicorn is started without an explicit port.
UVICORN_DEFAULT_PORT = 8000


@dataclass(frozen=True, slots=True)
class ProcessProfile:
    """A command that may be supervised as a long-running process."""

    executable: str
    prefix: tuple[str, ...]
    label: str
    #: Port when it can be known without guessing; None when only the tool
    #: itself decides (npm scripts read it from project config).
    default_port: int | None = None

    def matches(self, validated: ValidatedCommand) -> bool:
        request = validated.request
        return (
            request.executable == self.executable
            and request.args[: len(self.prefix)] == self.prefix
        )


#: The complete set. Anything not here cannot become a background process.
PROCESS_PROFILES: tuple[ProcessProfile, ...] = (
    ProcessProfile("npm", ("run", "dev"), "Next.js / npm development server"),
    ProcessProfile("npm", ("start",), "npm application"),
    ProcessProfile("npm", ("run", "start"), "npm application"),
    ProcessProfile(
        "uvicorn", (), "ASGI development server", default_port=UVICORN_DEFAULT_PORT
    ),
    ProcessProfile(
        "uv",
        ("run", "uvicorn"),
        "ASGI development server (uv)",
        default_port=UVICORN_DEFAULT_PORT,
    ),
)


@dataclass(frozen=True, slots=True)
class ValidatedProcess:
    """A background-eligible command, with its network details resolved."""

    command: ValidatedCommand
    profile: ProcessProfile
    host: str
    port: int | None

    @property
    def display(self) -> str:
        return self.command.display


def _network_details(validated: ValidatedCommand, profile: ProcessProfile) -> tuple[str, int | None]:
    """Host and port, taken from the command's own options where present.

    The command policy has already refused any non-local host, so whatever is
    here is a loopback address.
    """
    args = validated.request.args
    host = option_value(args, "--host") or DEFAULT_HOST
    raw_port = option_value(args, "--port")
    port = int(raw_port) if raw_port and raw_port.isdigit() else profile.default_port
    return host, port


def validate_process_command(command: str) -> ValidatedProcess:
    """Validate a command *and* confirm it may run in the background."""
    # Layer one: exactly the policy run_command uses. Not a copy of it.
    validated = validate_command_text(command)

    for profile in PROCESS_PROFILES:
        if profile.matches(validated):
            host, port = _network_details(validated, profile)
            return ValidatedProcess(
                command=validated, profile=profile, host=host, port=port
            )

    if not validated.long_running:
        raise CommandPolicyError(
            f"'{validated.display}' finishes on its own, so it does not need a "
            f"managed process. Use run_command instead."
        )
    raise CommandPolicyError(  # pragma: no cover - no such command today
        f"'{validated.display}' is not one of the commands that may run in the "
        f"background."
    )


def background_commands() -> list[str]:
    """The supported forms, for documentation and tests."""
    return [
        " ".join((profile.executable, *profile.prefix)) for profile in PROCESS_PROFILES
    ]
