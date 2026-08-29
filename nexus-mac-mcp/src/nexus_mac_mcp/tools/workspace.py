"""SAFE workspace intelligence: what kind of project is this?

Filesystem inspection only — nothing here runs a command. Presence of marker
files gives the project type; for the two ecosystems where the marker file is
ambiguous (``pyproject.toml``, ``package.json``) a bounded read of the manifest
narrows it down.
"""

from __future__ import annotations

from collections import Counter, deque
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
MARKER_NAMES = frozenset(marker for marker, _project_type in MARKER_FILES)

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
DEFAULT_OVERVIEW_DEPTH = 2
MAX_OVERVIEW_DEPTH = 4
MAX_OVERVIEW_ENTRIES = 120
MAX_OVERVIEW_LANGUAGES = 8

LANGUAGE_BY_SUFFIX: dict[str, str] = {
    ".py": "Python",
    ".js": "JavaScript",
    ".jsx": "React",
    ".ts": "TypeScript",
    ".tsx": "TypeScript/React",
    ".go": "Go",
    ".rs": "Rust",
    ".java": "Java",
    ".rb": "Ruby",
    ".php": "PHP",
    ".swift": "Swift",
    ".c": "C",
    ".h": "C/C++",
    ".cpp": "C++",
    ".css": "CSS",
    ".html": "HTML",
    ".sql": "SQL",
}

ENTRYPOINT_NAMES = frozenset(
    {
        "main.py",
        "app.py",
        "server.py",
        "index.js",
        "index.ts",
        "main.go",
        "main.rs",
        "manage.py",
        "Dockerfile",
        "docker-compose.yml",
        "docker-compose.yaml",
        "compose.yaml",
    }
)


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


def repo_overview(
    path: str,
    depth: int = DEFAULT_OVERVIEW_DEPTH,
    policy: FilesystemPolicy | None = None,
) -> dict[str, Any]:
    """Build a bounded, read-only map of a repository or project directory.

    This intentionally reports names and file extensions, never source
    contents. Secret files are omitted, ignored dependency/build directories
    are not traversed, and symlinks are never followed.
    """
    policy = policy_or_default(policy)
    if not 1 <= depth <= MAX_OVERVIEW_DEPTH:
        return _failure(
            f"Depth must be between 1 and {MAX_OVERVIEW_DEPTH}."
        )

    try:
        target = resolve_safe_path(path, policy=policy, require_directory=True)
    except PathError as exc:
        return _failure(str(exc))

    detected = detect_workspace(str(target), policy)
    structure: list[str] = []
    top_level_directories: list[str] = []
    top_level_files: list[str] = []
    entry_points: list[str] = []
    manifests: list[str] = []
    language_counts: Counter[str] = Counter()
    protected_files = 0
    truncated = False
    queue: deque[tuple[Path, int]] = deque([(target, 0)])
    effective_depth = min(depth, policy.max_depth)

    while queue:
        current, current_depth = queue.popleft()
        try:
            children = sorted(
                current.iterdir(), key=lambda item: item.name.casefold()
            )
        except (OSError, PermissionError):
            continue

        for child in children:
            if is_secret_file(child, policy):
                protected_files += 1
                continue

            kind = entry_type(child)
            if kind not in {"directory", "file", "symlink"}:
                continue
            if (
                kind == "directory"
                and not child.is_symlink()
                and should_skip_directory(child, policy)
            ):
                continue

            relative = str(child.relative_to(target))
            display = f"{relative}/" if kind == "directory" else relative
            structure.append(display)

            if current_depth == 0:
                if kind == "directory":
                    top_level_directories.append(child.name)
                else:
                    top_level_files.append(child.name)

            if child.name in ENTRYPOINT_NAMES:
                entry_points.append(relative)
            if current_depth == 0 and kind == "file" and (
                child.name in MARKER_NAMES
                or child.name in MANIFEST_HINTS
                or child.name in {"package-lock.json", "pnpm-lock.yaml", "yarn.lock"}
            ):
                manifests.append(child.name)

            if kind == "file":
                language = LANGUAGE_BY_SUFFIX.get(child.suffix.casefold())
                if language:
                    language_counts[language] += 1

            if len(structure) >= MAX_OVERVIEW_ENTRIES:
                truncated = True
                queue.clear()
                break

            if (
                kind == "directory"
                and not child.is_symlink()
                and current_depth < effective_depth
                and not should_skip_directory(child, policy)
            ):
                queue.append((child, current_depth + 1))

    languages = [
        language
        for language, _count in language_counts.most_common(MAX_OVERVIEW_LANGUAGES)
    ]
    return {
        "success": True,
        "path": str(target),
        "name": target.name or str(target),
        "is_git_repository": bool(detected.get("is_git_repository")),
        "project_types": detected.get("project_types", []),
        "manifests": manifests,
        "entry_points": entry_points,
        "languages": languages,
        "top_level_directories": top_level_directories,
        "top_level_files": top_level_files,
        "structure": structure,
        "protected_files": protected_files,
        "depth": effective_depth,
        "truncated": truncated,
    }
