"""Command policy — what may run, and in what shape.

This module decides. It never executes; :mod:`nexus_mac_mcp.tools.commands`
does that, and only for a request this module has already approved.

The design principle for this phase is that NEXUS must not become "LLM → shell".
So there is no shell anywhere, and being on the allowlist is not enough on its
own: every executable also has **explicit profiles** describing the exact shapes
it may be invoked in. ``npm`` being allowed does not make ``npm publish``
allowed; it makes ``npm run build`` allowed.

Three layers, in order:

1. **Lexical.** The command text must be drawn from a small character set. Shell
   metacharacters are not escaped or quoted — they are refused outright, so
   there is nothing to smuggle through.
2. **Allowlist + profile.** The executable must have a profile, and the
   arguments must match one of that profile's forms exactly.
3. **Blocklist.** A backstop for dangerous names and combinations. It is the
   *last* line, never the primary control.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Literal

#: Everything a permitted developer command needs, and nothing more. Note the
#: absence of & ; | > < $ ` ( ) \ ' " * ? and newlines: they cannot appear at
#: all, so `pytest && rm -rf /` is rejected before it is even tokenised.
_ALLOWED_TEXT = re.compile(r"^[A-Za-z0-9 ._/=+:@-]+$")

MAX_COMMAND_LENGTH = 512
MAX_ARGUMENTS = 24

#: Modules reachable through `python -m` / `uv run python -m`.
APPROVED_MODULES: frozenset[str] = frozenset(
    {"pytest", "unittest", "compileall", "json.tool"}
)

TrailingKind = Literal["none", "paths", "module"]
LeadingKind = Literal["asgi"]

#: Hosts a development server may bind to. A server NEXUS starts must not be
#: reachable from the network, so `0.0.0.0` and real addresses are refused.
LOCAL_HOSTS: frozenset[str] = frozenset({"127.0.0.1", "localhost", "::1"})

MIN_PORT = 1024
MAX_PORT = 65535

#: An ASGI target such as `app.main:app`. Written as a pattern rather than a
#: fixed list so no project's layout is baked into the policy.
_ASGI_TARGET = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*(\.[A-Za-z_][A-Za-z0-9_]*)*:[A-Za-z_][A-Za-z0-9_]*$")


def _is_local_host(value: str) -> bool:
    return value in LOCAL_HOSTS


def _is_allowed_port(value: str) -> bool:
    if not value.isdigit():
        return False
    return MIN_PORT <= int(value) <= MAX_PORT


def _is_asgi_target(value: str) -> bool:
    return bool(_ASGI_TARGET.match(value))


#: Validators for options that take a value, keyed by name so a form stays
#: comparable and printable.
OPTION_VALIDATORS: dict[str, Callable[[str], bool]] = {
    "local_host": _is_local_host,
    "port": _is_allowed_port,
}

LEADING_VALIDATORS: dict[str, Callable[[str], bool]] = {"asgi": _is_asgi_target}


class CommandPolicyError(Exception):
    """A command was refused. The message is safe to show the agent."""


@dataclass(frozen=True, slots=True)
class CommandRequest:
    """A command in structured form. Never a string handed to a shell."""

    executable: str
    args: tuple[str, ...] = ()

    @property
    def display(self) -> str:
        return " ".join((self.executable, *self.args))


@dataclass(frozen=True, slots=True)
class CommandForm:
    """One exact shape an executable may be invoked in."""

    prefix: tuple[str, ...] = ()
    leading: LeadingKind | None = None
    trailing: TrailingKind = "none"
    flags: frozenset[str] = frozenset()
    #: ``(option, validator key)`` pairs for flags that take a value, such as
    #: ``--port 8000``. The value is checked, never simply accepted.
    options: tuple[tuple[str, str], ...] = ()
    long_running: bool = False
    summary: str = ""

    def describe(self, executable: str) -> str:
        parts = [executable, *self.prefix]
        if self.leading:
            parts.append(f"<{self.leading} target>")
        if self.trailing == "module":
            # Naming the modules matters: told only that `-m` is allowed, a
            # caller will keep guessing modules that are never going to pass.
            parts.append(f"({'|'.join(sorted(APPROVED_MODULES))})")
        for option, _ in self.options:
            parts.append(f"[{option} ...]")
        return " ".join(parts)


@dataclass(frozen=True, slots=True)
class CommandProfile:
    """Everything permitted for one executable."""

    executable: str
    description: str
    forms: tuple[CommandForm, ...] = field(default_factory=tuple)


@dataclass(frozen=True, slots=True)
class ValidatedCommand:
    """A request that passed every check, plus the form it matched."""

    request: CommandRequest
    form: CommandForm

    @property
    def long_running(self) -> bool:
        return self.form.long_running

    @property
    def display(self) -> str:
        return self.request.display


# --- profiles --------------------------------------------------------------

_PYTEST_FLAGS = frozenset({"-q", "-v", "-vv", "-x", "--no-header", "--tb=short"})
_LOG_FLAGS = frozenset({"--oneline", "-n5", "-n10", "-n20", "--stat"})

PROFILES: dict[str, CommandProfile] = {
    "pytest": CommandProfile(
        executable="pytest",
        description="Run the Python test suite",
        forms=(
            CommandForm(trailing="paths", flags=_PYTEST_FLAGS, summary="run tests"),
        ),
    ),
    "uv": CommandProfile(
        executable="uv",
        description="Run a command inside the project's uv environment",
        forms=(
            CommandForm(
                prefix=("run", "pytest"),
                trailing="paths",
                flags=_PYTEST_FLAGS,
                summary="run tests with uv",
            ),
            CommandForm(
                prefix=("run", "python", "-m"),
                trailing="module",
                summary="run a Python module with uv",
            ),
            # The usual way to start a uv-managed FastAPI project: uvicorn
            # lives in the project's environment, not on the system path.
            CommandForm(
                prefix=("run", "uvicorn"),
                leading="asgi",
                flags=frozenset({"--reload"}),
                options=(("--host", "local_host"), ("--port", "port")),
                long_running=True,
                summary="start the development server with uv",
            ),
            CommandForm(
                prefix=("run", "python"),
                trailing="paths",
                summary="run a Python script with uv",
            ),
            CommandForm(prefix=("--version",), summary="report the uv version"),
        ),
    ),
    "npm": CommandProfile(
        executable="npm",
        description="Run a package script",
        forms=(
            CommandForm(
                prefix=("run", "dev"), long_running=True, summary="start the dev server"
            ),
            CommandForm(
                prefix=("run", "start"),
                long_running=True,
                summary="start the application",
            ),
            CommandForm(
                prefix=("start",), long_running=True, summary="start the application"
            ),
            CommandForm(prefix=("run", "build"), summary="build the project"),
            CommandForm(prefix=("run", "test"), summary="run the test script"),
            CommandForm(prefix=("run", "lint"), summary="lint the project"),
            CommandForm(prefix=("test",), summary="run the test script"),
            CommandForm(prefix=("--version",), summary="report the npm version"),
        ),
    ),
    "node": CommandProfile(
        executable="node",
        description="Run a JavaScript file",
        forms=(
            CommandForm(prefix=("--version",), summary="report the Node version"),
            CommandForm(trailing="paths", summary="run a script"),
        ),
    ),
    "python": CommandProfile(
        executable="python",
        description="Run Python",
        forms=(
            CommandForm(prefix=("-m",), trailing="module", summary="run a module"),
            CommandForm(prefix=("--version",), summary="report the Python version"),
            CommandForm(trailing="paths", summary="run a script"),
        ),
    ),
    "uvicorn": CommandProfile(
        executable="uvicorn",
        description="Run an ASGI development server",
        forms=(
            CommandForm(
                leading="asgi",
                flags=frozenset({"--reload"}),
                options=(("--host", "local_host"), ("--port", "port")),
                long_running=True,
                summary="start the development server",
            ),
        ),
    ),
    "git": CommandProfile(
        executable="git",
        description="Inspect the repository",
        forms=(
            CommandForm(prefix=("status",), summary="show the status"),
            CommandForm(prefix=("branch",), summary="list branches"),
            CommandForm(prefix=("log",), flags=_LOG_FLAGS, summary="show the log"),
            CommandForm(prefix=("diff", "--stat"), summary="summarise changes"),
            CommandForm(prefix=("--version",), summary="report the Git version"),
        ),
    ),
}
# `python3` behaves exactly like `python`.
PROFILES["python3"] = CommandProfile(
    executable="python3",
    description=PROFILES["python"].description,
    forms=PROFILES["python"].forms,
)

#: Deliberately absent: `npx` (fetches and runs arbitrary packages), every
#: installer (`pip install`, `uv add`, `npm install`), and anything that writes
#: to a repository. They have no profile, so they are refused.

# --- blocklist (the backstop, not the control) ----------------------------

BLOCKED_EXECUTABLES: frozenset[str] = frozenset(
    {
        "rm", "rmdir", "sudo", "su", "chmod", "chown", "chgrp", "kill", "pkill",
        "killall", "shutdown", "reboot", "halt", "diskutil", "defaults", "curl",
        "wget", "ssh", "scp", "sftp", "rsync", "dd", "mkfs", "mount", "umount",
        "launchctl", "osascript", "open", "sh", "bash", "zsh", "csh", "fish",
        "env", "eval", "exec", "nc", "netcat", "telnet", "crontab", "at",
        "security", "csrutil", "spctl", "softwareupdate", "installer", "pip",
        "pip3", "brew", "docker", "systemsetup", "networksetup", "dscl", "mv",
        "cp", "ln", "tee", "xargs", "find", "perl", "ruby", "php",
    }
)

#: Combinations refused even when the executable itself has a profile.
BLOCKED_COMBINATIONS: tuple[tuple[str, ...], ...] = (
    ("git", "push"), ("git", "reset"), ("git", "clean"), ("git", "checkout"),
    ("git", "commit"), ("git", "merge"), ("git", "rebase"), ("git", "rm"),
    ("git", "add"), ("git", "config"), ("git", "remote"), ("git", "fetch"),
    ("git", "pull"), ("git", "tag"), ("git", "stash"),
    ("npm", "publish"), ("npm", "install"), ("npm", "uninstall"), ("npm", "audit"),
    ("npm", "update"), ("npm", "link"), ("npm", "exec"),
    ("uv", "add"), ("uv", "remove"), ("uv", "pip"), ("uv", "publish"),
    ("uv", "sync"), ("uv", "tool"), ("uv", "self"),
    ("python", "-c"), ("python3", "-c"), ("node", "-e"), ("node", "--eval"),
)


# --- parsing ---------------------------------------------------------------


def parse_command(command: str) -> CommandRequest:
    """Turn command text into a structured request, or refuse it.

    Refuses anything outside the permitted character set, which is what makes
    shell injection a non-event: there is no quoting or escaping to get wrong
    because the dangerous characters never survive this function.
    """
    text = (command or "").strip()
    if not text:
        raise CommandPolicyError("A command is required.")
    if len(text) > MAX_COMMAND_LENGTH:
        raise CommandPolicyError("That command is too long.")
    if not _ALLOWED_TEXT.match(text):
        raise CommandPolicyError(
            "Commands may not contain shell characters such as & ; | > < $ ` or quotes."
        )

    tokens = text.split()
    if len(tokens) - 1 > MAX_ARGUMENTS:
        raise CommandPolicyError("That command has too many arguments.")

    executable, *args = tokens
    if "/" in executable:
        # A path would sidestep the allowlist and the controlled PATH lookup.
        raise CommandPolicyError("Commands must be given by name, not by path.")
    return CommandRequest(executable=executable, args=tuple(args))


# --- validation ------------------------------------------------------------


def _is_safe_relative_path(token: str) -> bool:
    """A path argument must stay inside the working directory."""
    if token.startswith("-") or token.startswith("/"):
        return False
    return ".." not in token.split("/")


def _matches(form: CommandForm, args: tuple[str, ...]) -> bool:
    if len(args) < len(form.prefix) or args[: len(form.prefix)] != form.prefix:
        return False
    rest = list(args[len(form.prefix) :])

    if form.leading is not None:
        if not rest or not LEADING_VALIDATORS[form.leading](rest[0]):
            return False
        rest = rest[1:]

    if form.trailing == "module":
        return len(rest) == 1 and rest[0] in APPROVED_MODULES

    options = dict(form.options)
    index = 0
    while index < len(rest):
        token = rest[index]
        if token in options:
            # An option's value is validated, never merely accepted.
            if index + 1 >= len(rest):
                return False
            if not OPTION_VALIDATORS[options[token]](rest[index + 1]):
                return False
            index += 2
            continue
        if token.startswith("-"):
            if token not in form.flags:
                return False
        elif form.trailing != "paths" or not _is_safe_relative_path(token):
            return False
        index += 1
    return True


def option_value(args: tuple[str, ...], option: str) -> str | None:
    """The value given for ``option``, if it appears."""
    for index, token in enumerate(args):
        if token == option and index + 1 < len(args):
            return args[index + 1]
    return None


def _check_blocklist(request: CommandRequest) -> None:
    """Second layer. Should never be the thing that saves us."""
    if request.executable in BLOCKED_EXECUTABLES:
        raise CommandPolicyError(f"'{request.executable}' is not an allowed command.")
    for combination in BLOCKED_COMBINATIONS:
        head, *tail = combination
        if request.executable == head and tuple(tail) == request.args[: len(tail)]:
            raise CommandPolicyError(
                f"'{' '.join(combination)}' is not allowed: it changes state."
            )


def validate(request: CommandRequest) -> ValidatedCommand:
    """Check a request against the policy, or raise ``CommandPolicyError``."""
    _check_blocklist(request)

    profile = PROFILES.get(request.executable)
    if profile is None:
        raise CommandPolicyError(
            f"'{request.executable}' is not an allowed command. "
            f"Allowed: {', '.join(sorted(PROFILES))}."
        )

    for form in profile.forms:
        if _matches(form, request.args):
            return ValidatedCommand(request=request, form=form)

    allowed = "; ".join(form.describe(request.executable) for form in profile.forms)
    raise CommandPolicyError(
        f"'{request.display}' is not an allowed form of '{request.executable}'. "
        f"Allowed forms: {allowed}."
    )


def validate_command_text(command: str) -> ValidatedCommand:
    """Parse and validate in one step."""
    return validate(parse_command(command))


def allowed_commands() -> dict[str, list[str]]:
    """The policy, for documentation and for tests to assert against."""
    return {
        name: [form.describe(name) for form in profile.forms]
        for name, profile in sorted(PROFILES.items())
    }
