"""The filesystem security layer.

Every filesystem tool goes through here. None of them re-implement any of these
checks, so there is exactly one place where "may the agent touch this path?" is
answered.

The primary control is an **allowlist**: a resolved path must sit inside one of
the configured roots (``$HOME`` by default). Everything else is defence in
depth — denied system directories, denied credential directories, and a
conservative secret-file policy.

Resolution happens *before* any check, so ``..`` and symlinks cannot be used to
step outside a root: a link pointing at ``/etc`` resolves to ``/etc`` and is
then rejected like any other outside path.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from fnmatch import fnmatch
from functools import lru_cache
from pathlib import Path

DEFAULT_MAX_FILE_BYTES = 100_000
DEFAULT_MAX_ENTRIES = 200
DEFAULT_MAX_MATCHES = 50
DEFAULT_MAX_DEPTH = 8
#: Ceiling on directories visited during a search, so a huge tree cannot hang a call.
DEFAULT_MAX_VISITS = 20_000

#: System locations no tool may enter, even if a root were configured over them.
#:
#: macOS resolves ``/tmp`` and ``/var`` into ``/private``, and the system temp
#: area lives at ``/private/var/folders``. Denying all of ``/private`` would
#: therefore deny ordinary temp directories, so the sensitive subtrees are named
#: individually instead. The allowlist is what keeps tools out of the rest.
#: Both the symlinked and resolved spellings are listed (``/etc`` resolves to
#: ``/private/etc``) so this holds up even when called on an unresolved path.
DENIED_PREFIXES: tuple[str, ...] = (
    "/System",
    "/Library",
    "/usr",
    "/bin",
    "/sbin",
    "/opt",
    "/cores",
    "/dev",
    "/proc",
    "/Network",
    "/Volumes",
    "/root",
    "/etc",
    "/var",
    "/private/etc",
    "/private/var/db",
    "/private/var/root",
    "/private/var/vm",
)

#: Denied relative to the user's home, wherever that is.
#:
#: ``~/Library`` sits *inside* the default root but holds Keychains, Mail,
#: Messages, browser history and application tokens. It is named here rather
#: than in :data:`DENIED_DIRECTORY_NAMES` so that an ordinary project folder
#: called "Library" stays readable.
#: ``.config/gh`` holds the GitHub CLI's OAuth token in ``hosts.yml`` — a name
#: far too generic to put in :data:`SECRET_FILE_PATTERNS`, so the directory is
#: named here instead.
DENIED_HOME_SUBPATHS: tuple[str, ...] = ("Library", ".config/gh")

#: Directory names that hold credentials. Never listed, searched or read into.
DENIED_DIRECTORY_NAMES: frozenset[str] = frozenset(
    {
        ".ssh",
        ".gnupg",
        ".aws",
        ".kube",
        ".docker",
        ".password-store",
        "Keychains",
    }
)

#: Conservative baseline, not a complete secret scanner. Matched case-insensitively
#: against the file name.
SECRET_FILE_PATTERNS: tuple[str, ...] = (
    ".env",
    ".env.*",
    "*.env",
    "*.pem",
    "*.key",
    "*.p12",
    "*.pfx",
    "*.keystore",
    "id_rsa*",
    "id_dsa*",
    "id_ecdsa*",
    "id_ed25519*",
    "credentials",
    "credentials.json",
    ".netrc",
    ".npmrc",
    ".pypirc",
    ".htpasswd",
    "*.jks",
    "secrets.json",
    "secrets.yaml",
    "secrets.yml",
    # Anything whose name ends in "credentials" — `.git-credentials` holds
    # `https://user:token@host` in plain text — and the matching `credentials.*`
    # spellings used by cargo, terraform and gcloud.
    "*credentials",
    "credentials.*",
    # Shell and REPL history. These are mode 0600 for a reason: a pasted
    # `export TOKEN=...` or `mysql -pSECRET` lives here forever. Anchored to
    # dotfiles so an ordinary `history.md` stays readable.
    ".*history",
    # Cloud/service configs that carry tokens rather than merely pointing at them.
    "rclone.conf",
    "*.keychain",
    "*.keychain-db",
    "*.token",
)

#: Skipped when walking a tree: large, uninteresting, or handled by other tools.
SKIP_DIRECTORY_NAMES: frozenset[str] = frozenset(
    {
        ".git",
        ".hg",
        ".svn",
        "node_modules",
        ".venv",
        "venv",
        "__pycache__",
        ".mypy_cache",
        ".pytest_cache",
        ".ruff_cache",
        ".next",
        ".turbo",
        ".gradle",
        "DerivedData",
        "Library",
        ".Trash",
        # Package-manager caches: large, and every hit in them is noise rather
        # than something the user was looking for.
        ".cache",
        ".local",
        ".npm",
        ".nvm",
        ".cargo",
        ".rustup",
        ".pyenv",
        ".conda",
        ".m2",
        ".terraform",
        "Pods",
    }
)


class PathError(Exception):
    """A path was rejected. The message is safe to show the agent."""


@dataclass(frozen=True, slots=True)
class FilesystemPolicy:
    """Where tools may look, and how much they may return."""

    roots: tuple[Path, ...]
    max_file_bytes: int = DEFAULT_MAX_FILE_BYTES
    max_entries: int = DEFAULT_MAX_ENTRIES
    max_matches: int = DEFAULT_MAX_MATCHES
    max_depth: int = DEFAULT_MAX_DEPTH
    max_visits: int = DEFAULT_MAX_VISITS
    denied_prefixes: tuple[str, ...] = DENIED_PREFIXES
    denied_home_subpaths: tuple[str, ...] = DENIED_HOME_SUBPATHS
    denied_directory_names: frozenset[str] = DENIED_DIRECTORY_NAMES
    secret_patterns: tuple[str, ...] = SECRET_FILE_PATTERNS
    skip_directory_names: frozenset[str] = SKIP_DIRECTORY_NAMES

    @property
    def primary_root(self) -> Path:
        return self.roots[0]

    def describe_roots(self) -> str:
        return ", ".join(str(root) for root in self.roots)


def _env_int(name: str, default: int) -> int:
    raw = os.getenv(name, "").strip()
    if not raw:
        return default
    try:
        value = int(raw)
    except ValueError:
        return default
    return value if value > 0 else default


def _env_roots() -> tuple[Path, ...]:
    raw = os.getenv("NEXUS_MAC_ALLOWED_ROOTS", "").strip()
    candidates = [item.strip() for item in raw.split(",") if item.strip()] or ["~"]
    roots: list[Path] = []
    for candidate in candidates:
        try:
            resolved = Path(candidate).expanduser().resolve()
        except (OSError, RuntimeError):
            continue
        if resolved.is_dir():
            roots.append(resolved)
    return tuple(roots) or (Path.home().resolve(),)


@lru_cache(maxsize=1)
def get_policy() -> FilesystemPolicy:
    """The policy built from the environment, cached for the process."""
    return FilesystemPolicy(
        roots=_env_roots(),
        max_file_bytes=_env_int("NEXUS_MAC_MAX_FILE_BYTES", DEFAULT_MAX_FILE_BYTES),
        max_entries=_env_int("NEXUS_MAC_MAX_ENTRIES", DEFAULT_MAX_ENTRIES),
        max_matches=_env_int("NEXUS_MAC_MAX_MATCHES", DEFAULT_MAX_MATCHES),
        max_depth=_env_int("NEXUS_MAC_MAX_DEPTH", DEFAULT_MAX_DEPTH),
    )


def policy_or_default(policy: FilesystemPolicy | None) -> FilesystemPolicy:
    return policy if policy is not None else get_policy()


# --- the checks ------------------------------------------------------------


def normalize_path(raw: str, policy: FilesystemPolicy | None = None) -> Path:
    """Turn caller text into an absolute, symlink-free path.

    Expands ``~``, interprets a relative path against the primary root (never
    against the server's working directory, which the caller cannot see), and
    resolves ``..`` and symlinks. This does **not** decide whether the path is
    allowed — :func:`resolve_safe_path` does that.
    """
    policy = policy_or_default(policy)
    text = (raw or "").strip()
    if not text:
        raise PathError("A path is required.")
    if "\x00" in text:
        raise PathError("That path is not valid.")

    candidate = Path(text).expanduser()
    if not candidate.is_absolute():
        candidate = policy.primary_root / candidate
    try:
        return candidate.resolve()
    except (OSError, RuntimeError) as exc:  # e.g. a symlink loop
        raise PathError("That path could not be resolved.") from exc


def is_allowed_path(path: Path, policy: FilesystemPolicy | None = None) -> bool:
    """Whether an already-resolved path may be touched at all."""
    policy = policy_or_default(policy)
    text = str(path)

    for prefix in policy.denied_prefixes:
        if text == prefix or text.startswith(f"{prefix}/"):
            return False
    if policy.denied_directory_names & {part for part in path.parts}:
        return False

    # Denied even though they sit inside the default root.
    try:
        home = Path.home().resolve()
    except (OSError, RuntimeError):  # pragma: no cover - no home configured
        home = None
    if home is not None:
        for subpath in policy.denied_home_subpaths:
            denied = home / subpath
            if path == denied or path.is_relative_to(denied):
                return False

    return any(path == root or path.is_relative_to(root) for root in policy.roots)


def is_secret_file(path: Path, policy: FilesystemPolicy | None = None) -> bool:
    """Whether a file's *name* marks it as holding credentials."""
    policy = policy_or_default(policy)
    name = path.name.casefold()
    return any(fnmatch(name, pattern.casefold()) for pattern in policy.secret_patterns)


def resolve_safe_path(
    raw: str,
    *,
    policy: FilesystemPolicy | None = None,
    must_exist: bool = True,
    require_directory: bool = False,
    require_file: bool = False,
) -> Path:
    """Resolve caller text to a path that is safe to act on, or raise.

    Rejection messages deliberately say what was refused without echoing back
    the resolved location of things outside the workspace.
    """
    policy = policy_or_default(policy)
    path = normalize_path(raw, policy)

    if not is_allowed_path(path, policy):
        raise PathError(
            f"That path is outside the allowed workspace ({policy.describe_roots()})."
        )
    if must_exist and not path.exists():
        raise PathError("That path does not exist.")
    if require_directory and path.exists() and not path.is_dir():
        raise PathError("That path is not a directory.")
    if require_file and path.exists() and not path.is_file():
        raise PathError("That path is not a file.")
    return path


def validate_file_size(path: Path, policy: FilesystemPolicy | None = None) -> int:
    """Return the file's size, or raise if it is too large to hand to a model."""
    policy = policy_or_default(policy)
    try:
        size = path.stat().st_size
    except OSError as exc:
        raise PathError("That file could not be read.") from exc
    if size > policy.max_file_bytes:
        raise PathError(
            f"That file is {size} bytes, over the {policy.max_file_bytes} byte limit."
        )
    return size


def should_skip_directory(path: Path, policy: FilesystemPolicy | None = None) -> bool:
    """Whether a directory should be walked past during a search."""
    policy = policy_or_default(policy)
    return path.name in policy.skip_directory_names or path.name in policy.denied_directory_names


def entry_type(path: Path) -> str:
    """Classify a directory entry without following links."""
    if path.is_symlink():
        return "symlink"
    if path.is_dir():
        return "directory"
    if path.is_file():
        return "file"
    return "other"
