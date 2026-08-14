"""CONFIRM tool: open an installed macOS application.

The safety property here is that the caller's text never reaches a command.
It is only ever used to *look up* an application in a set this server builds by
scanning the standard application directories. What gets launched is the
resolved bundle path we found ourselves, passed as a separate argv element to
``/usr/bin/open`` — no shell, no interpolation, no wildcards.

An unknown name is an error, never a best guess at a command.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from nexus_mac_mcp.core.platform import CommandError, run

OPEN = "/usr/bin/open"

#: Where macOS keeps applications. Anything outside these is not launchable.
APPLICATION_DIRECTORIES: tuple[Path, ...] = (
    Path("/Applications"),
    Path("/Applications/Utilities"),
    Path("/System/Applications"),
    Path("/System/Applications/Utilities"),
    Path.home() / "Applications",
)

MAX_NAME_LENGTH = 128


@dataclass(frozen=True, slots=True)
class Application:
    name: str
    path: Path


def _failure(error: str, **extra: Any) -> dict[str, Any]:
    return {"success": False, "error": error, **extra}


def installed_applications(
    directories: tuple[Path, ...] | None = None,
) -> list[Application]:
    """Every ``.app`` bundle in the standard locations, sorted by name."""
    found: dict[str, Application] = {}
    # Read the module constant at call time so it can be overridden in tests.
    for directory in directories if directories is not None else APPLICATION_DIRECTORIES:
        try:
            entries = sorted(directory.iterdir())
        except (OSError, PermissionError):
            continue
        for entry in entries:
            if entry.suffix != ".app" or not entry.is_dir():
                continue
            name = entry.stem
            found.setdefault(name.casefold(), Application(name=name, path=entry))
    return sorted(found.values(), key=lambda app: app.name)


def resolve_application(
    query: str, applications: list[Application] | None = None
) -> Application | None:
    """Match a human-written name to an installed application.

    Tries exact (case-insensitive), then prefix, then substring. A substring
    match is only accepted when it is unambiguous — "Microsoft" matching three
    different apps resolves to none of them.
    """
    candidates = applications if applications is not None else installed_applications()
    wanted = query.strip().casefold().removesuffix(".app")
    if not wanted:
        return None

    for app in candidates:
        if app.name.casefold() == wanted:
            return app

    prefixed = [app for app in candidates if app.name.casefold().startswith(wanted)]
    if len(prefixed) == 1:
        return prefixed[0]

    contained = [app for app in candidates if wanted in app.name.casefold()]
    if len(contained) == 1:
        return contained[0]
    return None


def open_application(application: str) -> dict[str, Any]:
    """Launch an installed application by name."""
    if not application or not application.strip():
        return _failure("Application name is required")
    if len(application) > MAX_NAME_LENGTH:
        return _failure("Application name is too long")

    resolved = resolve_application(application)
    if resolved is None:
        return _failure("Application not found", requested=application.strip())

    try:
        # The bundle path comes from our own scan, not from the caller.
        run([OPEN, "-a", str(resolved.path)], timeout=15.0)
    except CommandError as exc:
        return _failure(f"Could not open {resolved.name}: {exc}")

    return {
        "success": True,
        "application": resolved.name,
        "path": str(resolved.path),
        "source": "macos",
    }
