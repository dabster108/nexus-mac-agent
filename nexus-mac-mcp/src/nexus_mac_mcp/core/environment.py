"""The environment a command runs in.

A command never inherits this process's environment. That process was started
by the NEXUS backend, whose environment holds `GROQ_API_KEY`, `MISTRAL_API_KEY`
and whatever else the operator has exported — none of which any developer
command needs, and all of which would otherwise be one `printenv` away from the
model's context.

Instead the environment is *built*: a short list of variables inherited by name,
plus a fixed set this module forces. Everything else is dropped.
"""

from __future__ import annotations

import os
import shutil
from pathlib import Path

#: Inherited by name, because tools genuinely need them (caches, locale,
#: temporary files). None of them carry credentials.
INHERITED_VARIABLES: tuple[str, ...] = (
    "HOME",
    "USER",
    "LOGNAME",
    "LANG",
    "LC_ALL",
    "LC_CTYPE",
    "TMPDIR",
    "TZ",
)

#: Directories searched for an executable. A fixed list, not the caller's PATH,
#: so what runs cannot be changed by shadowing a name earlier in the path.
DEFAULT_PATH_DIRECTORIES: tuple[str, ...] = (
    "/usr/bin",
    "/bin",
    "/usr/local/bin",
    "/opt/homebrew/bin",
    "~/.local/bin",
    "~/.npm-global/bin",
)

#: Forced regardless of what the parent had.
FORCED_VARIABLES: dict[str, str] = {
    "TERM": "dumb",  # no escape codes in output handed to a model
    "NO_COLOR": "1",
    "CI": "1",  # keeps npm and friends non-interactive
    "PYTHONUNBUFFERED": "1",
    "PYTHONDONTWRITEBYTECODE": "1",
    "GIT_TERMINAL_PROMPT": "0",  # never block waiting for credentials
    "NPM_CONFIG_UPDATE_NOTIFIER": "false",
    "NPM_CONFIG_FUND": "false",
    "NPM_CONFIG_AUDIT": "false",
}


def path_directories() -> tuple[str, ...]:
    """The executable search path, overridable with ``NEXUS_MAC_COMMAND_PATH``."""
    raw = os.getenv("NEXUS_MAC_COMMAND_PATH", "").strip()
    entries = (
        [item.strip() for item in raw.split(":") if item.strip()]
        if raw
        else list(DEFAULT_PATH_DIRECTORIES)
    )
    return tuple(str(Path(entry).expanduser()) for entry in entries)


def build_environment() -> dict[str, str]:
    """The complete environment a command will see."""
    environment = {
        name: os.environ[name] for name in INHERITED_VARIABLES if name in os.environ
    }
    environment.update(FORCED_VARIABLES)
    environment["PATH"] = ":".join(path_directories())
    return environment


def resolve_executable(name: str) -> str | None:
    """Find an executable on the controlled path, or return None."""
    return shutil.which(name, path=":".join(path_directories()))


def describe_environment() -> dict[str, object]:
    """What a command inherits, for documentation and tests."""
    return {
        "inherited": list(INHERITED_VARIABLES),
        "forced": dict(FORCED_VARIABLES),
        "path": list(path_directories()),
    }
