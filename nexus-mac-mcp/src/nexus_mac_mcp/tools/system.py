"""SAFE system tools: battery, machine info, running processes.

All read-only. Each reads the real machine — nothing here returns placeholder
data, and a reading that cannot be taken is reported as a failure rather than
guessed at.
"""

from __future__ import annotations

import os
import platform
import re
import socket
from typing import Any

from nexus_mac_mcp.core.platform import CommandError, run

PMSET = "/usr/bin/pmset"
PS = "/bin/ps"

MAX_PROCESSES = 50
DEFAULT_PROCESSES = 15

_BATTERY_RE = re.compile(
    r"(?P<percentage>\d{1,3})%;\s*(?P<state>[^;]+);\s*(?P<remaining>[^;]*)"
)
#: pmset appends "present: true" to the last field; it is not part of the estimate.
_PRESENT_SUFFIX_RE = re.compile(r"\s*present:.*$", re.IGNORECASE)
_TIME_REMAINING_RE = re.compile(r"^\d{1,2}:\d{2}")


def _failure(error: str) -> dict[str, Any]:
    return {"success": False, "error": error}


def _time_remaining(field: str) -> str | None:
    """The estimate, or None when macOS has not worked one out."""
    cleaned = _PRESENT_SUFFIX_RE.sub("", field).strip()
    return cleaned if _TIME_REMAINING_RE.match(cleaned) else None


def battery_status() -> dict[str, Any]:
    """Read the battery through ``pmset``."""
    try:
        output = run([PMSET, "-g", "batt"]).stdout
    except CommandError as exc:
        return _failure(str(exc))

    match = _BATTERY_RE.search(output)
    if match is None:
        return _failure("No battery was found on this Mac.")

    state = match.group("state").strip().lower()
    return {
        "success": True,
        "percentage": int(match.group("percentage")),
        "charging": state == "charging",
        "state": state,
        "time_remaining": _time_remaining(match.group("remaining")),
        "power_source": "AC Power" if "AC Power" in output else "Battery Power",
        "source": "macos",
    }


def system_info() -> dict[str, Any]:
    """Basic facts about this Mac.

    Deliberately limited: no serial number, no user account details, no network
    addresses. The hostname is the short name, not the fully-qualified one.
    """
    return {
        "success": True,
        "platform": "macOS",
        "os_version": platform.mac_ver()[0] or platform.release(),
        "kernel_version": platform.release(),
        "architecture": platform.machine(),
        "hostname": socket.gethostname().removesuffix(".local"),
        "cpu_count": os.cpu_count(),
        "python_version": platform.python_version(),
        "source": "macos",
    }


def running_processes(limit: int = DEFAULT_PROCESSES) -> dict[str, Any]:
    """A short summary of the busiest processes.

    Reports executable names only. Full command lines are not returned: they
    routinely carry file paths, tokens and other things the agent has no need
    for. This tool cannot stop or signal anything.
    """
    if limit < 1:
        return _failure("limit must be at least 1.")
    limit = min(limit, MAX_PROCESSES)

    try:
        # -c reports the executable name rather than the full command line.
        output = run([PS, "-Aco", "pid,pcpu,pmem,comm", "-r"]).stdout
    except CommandError as exc:
        return _failure(str(exc))

    processes: list[dict[str, Any]] = []
    for line in output.splitlines()[1:]:  # skip the header
        parts = line.split(None, 3)
        if len(parts) < 4:
            continue
        pid, cpu, mem, name = parts
        try:
            processes.append(
                {
                    "pid": int(pid),
                    "cpu_percent": float(cpu),
                    "memory_percent": float(mem),
                    "name": name.strip(),
                }
            )
        except ValueError:  # pragma: no cover - malformed ps row
            continue
        if len(processes) >= limit:
            break

    return {
        "success": True,
        "count": len(processes),
        "processes": processes,
        "source": "macos",
    }
