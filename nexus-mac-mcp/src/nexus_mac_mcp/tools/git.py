"""SAFE Git tools — read-only, and explicitly so.

This is **not** a terminal. There is no way to pass a subcommand, a flag or a
refspec through these tools: each one builds a fixed argv list, and the only
caller-supplied value that reaches Git is a path already validated against the
filesystem policy (plus integer limits, which cannot be anything but numbers).

Every command here only reads. Nothing writes, moves a ref, stages, commits or
touches the network. Adding a mutating operation means adding it deliberately,
with its own permission level — not widening one of these.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from nexus_mac_mcp.core.filesystem import (
    FilesystemPolicy,
    PathError,
    is_allowed_path,
    policy_or_default,
    resolve_safe_path,
)
from nexus_mac_mcp.core.platform import CommandError, run

GIT = "/usr/bin/git"

#: `--no-optional-locks` keeps a read from writing index files;
#: `--no-pager` stops Git trying to page output at a terminal that is not there.
BASE_ARGS: tuple[str, ...] = ("--no-optional-locks", "--no-pager")

DEFAULT_LOG_LIMIT = 10
MAX_LOG_LIMIT = 50
MAX_STATUS_FILES = 100
MAX_BRANCHES = 100
MAX_DIFF_LINES = 100

_FIELD_SEPARATOR = "\x1f"
_NO_COMMITS = "does not have any commits yet"


def _failure(error: str) -> dict[str, Any]:
    return {"success": False, "error": error}


def repository_root(path: Path, policy: FilesystemPolicy) -> Path | None:
    """Walk up to the directory holding ``.git``, without leaving the workspace."""
    for candidate in (path, *path.parents):
        if not is_allowed_path(candidate, policy):
            return None
        if (candidate / ".git").exists():
            return candidate
    return None


def _prepare(path: str, policy: FilesystemPolicy | None) -> tuple[Path, FilesystemPolicy]:
    """Resolve the argument to a repository root, or raise ``PathError``."""
    policy = policy_or_default(policy)
    target = resolve_safe_path(path, policy=policy, require_directory=True)
    root = repository_root(target, policy)
    if root is None:
        raise PathError("That directory is not inside a Git repository.")
    return root, policy


def _git(root: Path, *args: str, timeout: float = 10.0) -> str:
    return run([GIT, *BASE_ARGS, "-C", str(root), *args], timeout=timeout).stdout


def git_status(path: str, policy: FilesystemPolicy | None = None) -> dict[str, Any]:
    """Branch, tracking position and the working-tree changes."""
    try:
        root, _ = _prepare(path, policy)
        output = _git(root, "status", "--porcelain=v1", "--branch")
    except PathError as exc:
        return _failure(str(exc))
    except CommandError as exc:
        return _failure(str(exc))

    branch: str | None = None
    ahead = behind = 0
    changes: list[dict[str, str]] = []

    for line in output.splitlines():
        if line.startswith("## "):
            header = line[3:]
            branch = header.split("...")[0].strip()
            if "ahead " in header:
                ahead = _tracking_count(header, "ahead ")
            if "behind " in header:
                behind = _tracking_count(header, "behind ")
            continue
        if len(line) > 3:
            changes.append({"status": line[:2].strip() or "?", "path": line[3:]})

    return {
        "success": True,
        "path": str(root),
        "branch": branch,
        "ahead": ahead,
        "behind": behind,
        "clean": not changes,
        "changes": changes[:MAX_STATUS_FILES],
        "changed_files": len(changes),
        "truncated": len(changes) > MAX_STATUS_FILES,
    }


def _tracking_count(header: str, marker: str) -> int:
    try:
        tail = header.split(marker, 1)[1]
        digits = ""
        for character in tail:
            if character.isdigit():
                digits += character
            else:
                break
        return int(digits) if digits else 0
    except (IndexError, ValueError):  # pragma: no cover - defensive
        return 0


def git_branch(path: str, policy: FilesystemPolicy | None = None) -> dict[str, Any]:
    """The local branches, and which one is checked out."""
    try:
        root, _ = _prepare(path, policy)
        # Two plain reads rather than one clever format: branch names may
        # legally contain the separators a combined format would need.
        output = _git(root, "branch", "--list", "--format=%(refname:short)")
        current = _git(root, "branch", "--show-current").strip() or None
    except PathError as exc:
        return _failure(str(exc))
    except CommandError as exc:
        return _failure(str(exc))

    branches = [line.strip() for line in output.splitlines() if line.strip()]

    return {
        "success": True,
        "path": str(root),
        "current": current,
        "branches": branches[:MAX_BRANCHES],
        "count": len(branches),
        "truncated": len(branches) > MAX_BRANCHES,
    }


def git_log(
    path: str, limit: int = DEFAULT_LOG_LIMIT, policy: FilesystemPolicy | None = None
) -> dict[str, Any]:
    """Recent commits, newest first."""
    if limit < 1:
        return _failure("limit must be at least 1.")
    limit = min(limit, MAX_LOG_LIMIT)

    try:
        root, _ = _prepare(path, policy)
        output = _git(
            root,
            "log",
            f"-n{limit}",
            f"--pretty=format:%h{_FIELD_SEPARATOR}%an{_FIELD_SEPARATOR}%ar{_FIELD_SEPARATOR}%s",
        )
    except PathError as exc:
        return _failure(str(exc))
    except CommandError as exc:
        if _NO_COMMITS in str(exc):
            return {"success": True, "path": path, "commits": [], "count": 0}
        return _failure(str(exc))

    commits: list[dict[str, str]] = []
    for line in output.splitlines():
        parts = line.split(_FIELD_SEPARATOR)
        if len(parts) != 4:
            continue
        commits.append(
            {
                "hash": parts[0],
                "author": parts[1],
                "when": parts[2],
                "subject": parts[3],
            }
        )

    return {
        "success": True,
        "path": str(root),
        "commits": commits,
        "count": len(commits),
    }


def git_diff(
    path: str, staged: bool = False, policy: FilesystemPolicy | None = None
) -> dict[str, Any]:
    """A summary of what changed — file names and line counts, not the patch."""
    try:
        root, _ = _prepare(path, policy)
        args = ["diff", "--stat"]
        if staged:
            args.append("--cached")
        output = _git(root, *args)
    except PathError as exc:
        return _failure(str(exc))
    except CommandError as exc:
        return _failure(str(exc))

    lines = [line for line in output.splitlines() if line.strip()]
    return {
        "success": True,
        "path": str(root),
        "staged": staged,
        "summary": lines[:MAX_DIFF_LINES],
        "changed": bool(lines),
        "truncated": len(lines) > MAX_DIFF_LINES,
    }
