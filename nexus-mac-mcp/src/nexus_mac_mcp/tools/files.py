"""SAFE filesystem tools: list, search, read.

All three are read-only and all three delegate every safety decision to
:mod:`nexus_mac_mcp.core.filesystem`. Nothing here re-implements a check.

Secret files follow one consistent rule: they can be *seen* — a listing or a
search will show the name, flagged — but they can never be *read*. Directories
that exist to hold credentials (``.ssh`` and friends) are not entered at all.
"""

from __future__ import annotations

from collections import deque
from pathlib import Path
from typing import Any

from nexus_mac_mcp.core.filesystem import (
    FilesystemPolicy,
    PathError,
    entry_type,
    is_secret_file,
    policy_or_default,
    resolve_safe_path,
    should_skip_directory,
    validate_file_size,
)

#: Read in one go for the binary sniff; files above the limit are rejected anyway.
_SNIFF_BYTES = 8192


def _failure(error: str) -> dict[str, Any]:
    return {"success": False, "error": error}


def list_directory(
    path: str, policy: FilesystemPolicy | None = None
) -> dict[str, Any]:
    """List one directory. Does not recurse."""
    policy = policy_or_default(policy)
    try:
        target = resolve_safe_path(path, policy=policy, require_directory=True)
        entries = sorted(
            target.iterdir(), key=lambda item: (not item.is_dir(), item.name.casefold())
        )
    except PathError as exc:
        return _failure(str(exc))
    except OSError:
        return _failure("That directory could not be read.")

    listed: list[dict[str, Any]] = []
    for item in entries[: policy.max_entries]:
        entry: dict[str, Any] = {"name": item.name, "type": entry_type(item)}
        if is_secret_file(item, policy):
            # Visible, but read_file will refuse it.
            entry["protected"] = True
        listed.append(entry)

    return {
        "success": True,
        "path": str(target),
        "entries": listed,
        "count": len(listed),
        "truncated": len(entries) > len(listed),
    }


def search_files(
    query: str,
    path: str | None = None,
    policy: FilesystemPolicy | None = None,
) -> dict[str, Any]:
    """Find files and directories whose name contains ``query``.

    Breadth-first from ``path`` (the primary root by default), bounded by depth,
    number of directories visited, and number of matches, so a large tree cannot
    stall the agent or flood its context.
    """
    policy = policy_or_default(policy)
    needle = (query or "").strip().casefold()
    if not needle:
        return _failure("A search query is required.")

    try:
        root = resolve_safe_path(
            path if path else str(policy.primary_root),
            policy=policy,
            require_directory=True,
        )
    except PathError as exc:
        return _failure(str(exc))

    matches: list[dict[str, Any]] = []
    queue: deque[tuple[Path, int]] = deque([(root, 0)])
    visited = 0
    truncated = False

    while queue:
        current, depth = queue.popleft()
        visited += 1
        if visited > policy.max_visits:
            truncated = True
            break
        try:
            children = sorted(current.iterdir(), key=lambda item: item.name.casefold())
        except (OSError, PermissionError):
            continue

        for child in children:
            if needle in child.name.casefold():
                match: dict[str, Any] = {"path": str(child), "type": entry_type(child)}
                if is_secret_file(child, policy):
                    match["protected"] = True
                matches.append(match)
                if len(matches) >= policy.max_matches:
                    truncated = True
                    queue.clear()
                    break
            # Never descend through a link: it could leave the workspace.
            if (
                child.is_dir()
                and not child.is_symlink()
                and depth + 1 <= policy.max_depth
                and not should_skip_directory(child, policy)
            ):
                queue.append((child, depth + 1))

    return {
        "success": True,
        "query": query.strip(),
        "path": str(root),
        "matches": matches,
        "count": len(matches),
        "truncated": truncated,
    }


def read_file(path: str, policy: FilesystemPolicy | None = None) -> dict[str, Any]:
    """Read a text file's contents."""
    policy = policy_or_default(policy)
    try:
        target = resolve_safe_path(path, policy=policy, require_file=True)
    except PathError as exc:
        return _failure(str(exc))

    if is_secret_file(target, policy):
        return _failure("That file may hold credentials, so it cannot be read.")

    try:
        size = validate_file_size(target, policy)
    except PathError as exc:
        return _failure(str(exc))

    try:
        raw = target.read_bytes()
    except (OSError, PermissionError):
        return _failure("That file could not be read.")

    if b"\x00" in raw[:_SNIFF_BYTES]:
        return _failure("That file looks binary, so it was not read.")
    try:
        content = raw.decode("utf-8")
    except UnicodeDecodeError:
        return _failure("That file is not valid UTF-8 text, so it was not read.")

    return {
        "success": True,
        "path": str(target),
        "content": content,
        "size": size,
    }
