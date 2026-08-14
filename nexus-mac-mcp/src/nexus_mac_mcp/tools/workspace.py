"""SAFE workspace intelligence: what kind of project is this?

Filesystem inspection only — nothing here runs a command. Presence of marker
files gives the project type; for the two ecosystems where the marker file is
ambiguous (``pyproject.toml``, ``package.json``) a bounded read of the manifest
narrows it down.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from nexus_mac_mcp.core.filesystem import (
    FilesystemPolicy,
    PathError,
    policy_or_default,
    resolve_safe_path,
)

#: Marker file (or glob) -> project type.
MARKER_FILES: tuple[tuple[str, str], ...] = (
    ("pyproject.toml", "python"),
    ("requirements.txt", "python"),
    ("setup.py", "python"),
    ("Pipfile", "python"),
    ("uv.lock", "uv"),
    ("poetry.lock", "poetry"),
    ("package.json", "node"),
    ("tsconfig.json", "typescript"),
    ("go.mod", "go"),
    ("Cargo.toml", "rust"),
    ("Gemfile", "ruby"),
    ("pom.xml", "java"),
    ("build.gradle", "java"),
    ("Dockerfile", "docker"),
    ("docker-compose.yml", "docker"),
    ("docker-compose.yaml", "docker"),
    ("compose.yaml", "docker"),
    ("Makefile", "make"),
)

MARKER_GLOBS: tuple[tuple[str, str], ...] = (
    ("next.config.*", "nextjs"),
    ("vite.config.*", "vite"),
    ("svelte.config.*", "svelte"),
    ("tailwind.config.*", "tailwind"),
)

#: Substrings looked for inside a manifest, mapped to the type they imply.
MANIFEST_HINTS: dict[str, tuple[tuple[str, str], ...]] = {
    "pyproject.toml": (
        ("fastapi", "fastapi"),
        ("django", "django"),
        ("flask", "flask"),
        ("langgraph", "langgraph"),
        ("mcp", "mcp"),
    ),
    "package.json": (
        ('"next"', "nextjs"),
        ('"react"', "react"),
        ('"vue"', "vue"),
        ('"svelte"', "svelte"),
        ('"express"', "express"),
        ('"typescript"', "typescript"),
    ),
}

#: Manifests are small; refuse to sniff anything unreasonable.
MAX_MANIFEST_BYTES = 64_000
MAX_LISTED_FILES = 25


def _failure(error: str) -> dict[str, Any]:
    return {"success": False, "error": error}


def _read_manifest(path: Path) -> str:
    try:
        if path.stat().st_size > MAX_MANIFEST_BYTES:
            return ""
        return path.read_text(encoding="utf-8", errors="ignore").casefold()
    except (OSError, PermissionError):
        return ""


def detect_workspace(
    path: str, policy: FilesystemPolicy | None = None
) -> dict[str, Any]:
    """Identify a developer project from the files it contains."""
    policy = policy_or_default(policy)
    try:
        target = resolve_safe_path(path, policy=policy, require_directory=True)
    except PathError as exc:
        return _failure(str(exc))

    found: list[str] = []
    types: list[str] = []

    def note(name: str, project_type: str) -> None:
        if name not in found:
            found.append(name)
        if project_type not in types:
            types.append(project_type)

    for marker, project_type in MARKER_FILES:
        if (target / marker).is_file():
            note(marker, project_type)

    for pattern, project_type in MARKER_GLOBS:
        for match in sorted(target.glob(pattern)):
            if match.is_file():
                note(match.name, project_type)
                break

    for manifest, hints in MANIFEST_HINTS.items():
        manifest_path = target / manifest
        if not manifest_path.is_file():
            continue
        content = _read_manifest(manifest_path)
        for needle, project_type in hints:
            if needle in content and project_type not in types:
                types.append(project_type)

    is_git = (target / ".git").exists()
    if is_git and ".git" not in found:
        found.append(".git")

    return {
        "success": True,
        "path": str(target),
        "is_git_repository": is_git,
        "project_types": types,
        "files": found[:MAX_LISTED_FILES],
        "is_project": bool(types) or is_git,
    }
