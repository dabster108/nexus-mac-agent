"""The filesystem security layer.

These are the tests that matter most in this phase: everything the agent must
*not* be able to reach.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from nexus_mac_mcp.core.filesystem import (
    FilesystemPolicy,
    PathError,
    is_allowed_path,
    is_secret_file,
    normalize_path,
    resolve_safe_path,
    validate_file_size,
)
from nexus_mac_mcp.tools import files


# --- traversal -------------------------------------------------------------


def test_dot_dot_cannot_escape_the_root(policy: FilesystemPolicy, workspace_dir: Path) -> None:
    (workspace_dir / "project").mkdir()

    with pytest.raises(PathError, match="outside the allowed workspace"):
        resolve_safe_path(f"{workspace_dir}/project/../../..", policy=policy)


def test_a_deep_traversal_string_cannot_escape(policy: FilesystemPolicy, workspace_dir: Path) -> None:
    with pytest.raises(PathError, match="outside the allowed workspace"):
        resolve_safe_path(f"{workspace_dir}/../../../../../../etc/passwd", policy=policy)


def test_an_absolute_path_outside_the_root_is_rejected(
    policy: FilesystemPolicy, outside: Path
) -> None:
    with pytest.raises(PathError, match="outside the allowed workspace"):
        resolve_safe_path(str(outside / "secret.txt"), policy=policy)


@pytest.mark.parametrize(
    "system_path",
    ["/etc/passwd", "/System/Library", "/usr/bin/env", "/private/etc/hosts", "/dev/null"],
)
def test_system_locations_are_rejected(system_path: str, policy: FilesystemPolicy) -> None:
    with pytest.raises(PathError):
        resolve_safe_path(system_path, policy=policy)


def test_system_locations_are_rejected_even_when_a_root_covers_them() -> None:
    """The deny list is not just a consequence of the allowlist."""
    everything = FilesystemPolicy(roots=(Path("/"),))

    assert is_allowed_path(Path("/etc/passwd"), everything) is False
    assert is_allowed_path(Path("/System/Library/Keychains"), everything) is False
    assert is_allowed_path(Path("/usr/bin/git"), everything) is False


def test_credential_directories_are_rejected() -> None:
    home = Path.home().resolve()
    at_home = FilesystemPolicy(roots=(home,))

    for denied in (".ssh/id_rsa", ".aws/credentials", ".gnupg/secring.gpg", ".kube/config"):
        assert is_allowed_path(home / denied, at_home) is False, denied


def test_an_empty_path_is_rejected(policy: FilesystemPolicy) -> None:
    for empty in ("", "   "):
        with pytest.raises(PathError, match="path is required"):
            normalize_path(empty, policy)


def test_a_null_byte_is_rejected(policy: FilesystemPolicy) -> None:
    with pytest.raises(PathError):
        normalize_path("/tmp/evil\x00.txt", policy)


def test_a_relative_path_resolves_against_the_root_not_the_cwd(
    policy: FilesystemPolicy, workspace_dir: Path
) -> None:
    (workspace_dir / "notes.md").write_text("hi")

    resolved = resolve_safe_path("notes.md", policy=policy)

    assert resolved == workspace_dir / "notes.md"


# --- symlinks --------------------------------------------------------------


def test_a_symlink_out_of_the_root_is_rejected(
    policy: FilesystemPolicy, workspace_dir: Path, outside: Path
) -> None:
    (workspace_dir / "link").symlink_to(outside)

    with pytest.raises(PathError, match="outside the allowed workspace"):
        resolve_safe_path(f"{workspace_dir}/link/secret.txt", policy=policy)


def test_a_symlinked_file_out_of_the_root_is_rejected(
    policy: FilesystemPolicy, workspace_dir: Path, outside: Path
) -> None:
    (workspace_dir / "leak.txt").symlink_to(outside / "secret.txt")

    result = files.read_file(f"{workspace_dir}/leak.txt", policy)

    assert result["success"] is False
    assert "outside the allowed workspace" in result["error"]


def test_a_symlink_to_a_system_file_is_rejected(
    policy: FilesystemPolicy, workspace_dir: Path
) -> None:
    (workspace_dir / "passwd").symlink_to("/etc/passwd")

    result = files.read_file(f"{workspace_dir}/passwd", policy)

    assert result["success"] is False


def test_a_symlink_inside_the_root_still_works(
    policy: FilesystemPolicy, workspace_dir: Path
) -> None:
    (workspace_dir / "real").mkdir()
    (workspace_dir / "real" / "note.md").write_text("inside")
    (workspace_dir / "alias").symlink_to(workspace_dir / "real")

    result = files.read_file(f"{workspace_dir}/alias/note.md", policy)

    assert result["success"] is True
    assert result["content"] == "inside"


def test_search_does_not_follow_symlinks_out(
    policy: FilesystemPolicy, workspace_dir: Path, outside: Path
) -> None:
    (outside / "findme.txt").write_text("x")
    (workspace_dir / "link").symlink_to(outside)

    result = files.search_files("findme", str(workspace_dir), policy)

    assert result["success"] is True
    assert result["matches"] == []


# --- secret files ----------------------------------------------------------


@pytest.mark.parametrize(
    "name",
    [
        ".env",
        ".env.local",
        ".env.production",
        "id_rsa",
        "id_ed25519",
        "server.pem",
        "private.key",
        "credentials.json",
        ".netrc",
        ".npmrc",
        "keystore.jks",
        "secrets.yaml",
    ],
)
def test_secret_files_are_recognised(name: str) -> None:
    assert is_secret_file(Path(f"/somewhere/{name}")) is True


@pytest.mark.parametrize("name", ["README.md", "main.py", "package.json", "env.py", "keys.md"])
def test_ordinary_files_are_not_flagged(name: str) -> None:
    assert is_secret_file(Path(f"/somewhere/{name}")) is False


@pytest.mark.parametrize(
    "name",
    [
        # Plain-text `https://user:token@host`, and the cargo/terraform/gcloud
        # spellings of the same idea.
        ".git-credentials",
        "credentials.toml",
        "credentials.tfrc.json",
        # Shell and REPL history: a pasted `export TOKEN=...` lives here forever.
        ".zsh_history",
        ".bash_history",
        ".python_history",
        ".mysql_history",
        ".psql_history",
        # Service configs that carry a token rather than pointing at one.
        "rclone.conf",
        "login.keychain-db",
        "github.token",
    ],
)
def test_credential_bearing_files_found_in_the_audit_are_blocked(name: str) -> None:
    """Phase 9: every one of these was readable, inside $HOME and unflagged."""
    assert is_secret_file(Path(f"/somewhere/{name}")) is True


@pytest.mark.parametrize(
    "name", ["history.md", ".gitconfig", "credentials_helper.py", "my.credentials.md"]
)
def test_the_widened_secret_patterns_do_not_catch_ordinary_files(name: str) -> None:
    assert is_secret_file(Path(f"/somewhere/{name}")) is False


def test_the_github_cli_token_directory_is_denied() -> None:
    """`hosts.yml` is too generic a name to blocklist, so the directory is."""
    assert is_allowed_path(Path.home() / ".config/gh/hosts.yml") is False
    # Neighbouring config stays reachable.
    assert is_allowed_path(Path.home() / ".config/myapp/settings.json") is True


def test_secret_names_match_regardless_of_case() -> None:
    assert is_secret_file(Path("/x/ID_RSA")) is True
    assert is_secret_file(Path("/x/Server.PEM")) is True


@pytest.mark.parametrize("name", [".env", ".env.local", "id_rsa", "deploy.pem"])
def test_a_secret_file_cannot_be_read(
    name: str, policy: FilesystemPolicy, workspace_dir: Path
) -> None:
    (workspace_dir / name).write_text("SECRET_TOKEN=abc123")

    result = files.read_file(f"{workspace_dir}/{name}", policy)

    assert result["success"] is False
    assert "credentials" in result["error"]
    assert "abc123" not in str(result)


def test_a_secret_file_is_visible_but_flagged(
    policy: FilesystemPolicy, workspace_dir: Path
) -> None:
    (workspace_dir / ".env").write_text("SECRET=1")
    (workspace_dir / "README.md").write_text("hi")

    listed = files.list_directory(str(workspace_dir), policy)

    by_name = {entry["name"]: entry for entry in listed["entries"]}
    assert by_name[".env"]["protected"] is True
    assert "protected" not in by_name["README.md"]


# --- size and volume limits -----------------------------------------------


def test_an_oversized_file_is_rejected(policy: FilesystemPolicy, workspace_dir: Path) -> None:
    big = workspace_dir / "big.log"
    big.write_text("x" * 5000)  # policy allows 1024

    result = files.read_file(str(big), policy)

    assert result["success"] is False
    assert "over the 1024 byte limit" in result["error"]


def test_validate_file_size_returns_the_size(policy: FilesystemPolicy, workspace_dir: Path) -> None:
    small = workspace_dir / "small.txt"
    small.write_text("12345")

    assert validate_file_size(small, policy) == 5


def test_a_binary_file_is_rejected(policy: FilesystemPolicy, workspace_dir: Path) -> None:
    binary = workspace_dir / "app.bin"
    binary.write_bytes(b"\x7fELF\x00\x01\x02\x03")

    result = files.read_file(str(binary), policy)

    assert result["success"] is False
    assert "binary" in result["error"]


def test_invalid_utf8_is_rejected(policy: FilesystemPolicy, workspace_dir: Path) -> None:
    bad = workspace_dir / "bad.txt"
    bad.write_bytes(b"\xff\xfe\xfd valid-looking")

    result = files.read_file(str(bad), policy)

    assert result["success"] is False


def test_directory_listings_are_capped(policy: FilesystemPolicy, workspace_dir: Path) -> None:
    for index in range(20):
        (workspace_dir / f"file{index:02d}.txt").write_text("x")

    result = files.list_directory(str(workspace_dir), policy)

    assert result["count"] == 5  # policy.max_entries
    assert result["truncated"] is True


def test_search_results_are_capped(policy: FilesystemPolicy, workspace_dir: Path) -> None:
    for index in range(20):
        (workspace_dir / f"match{index:02d}.txt").write_text("x")

    result = files.search_files("match", str(workspace_dir), policy)

    assert result["count"] == 3  # policy.max_matches
    assert result["truncated"] is True


def test_search_respects_max_depth(policy: FilesystemPolicy, workspace_dir: Path) -> None:
    deep = workspace_dir / "a" / "b" / "c" / "d" / "e"
    deep.mkdir(parents=True)
    (deep / "buried.txt").write_text("x")

    result = files.search_files("buried", str(workspace_dir), policy)

    assert result["matches"] == []


def test_search_skips_noisy_directories(policy: FilesystemPolicy, workspace_dir: Path) -> None:
    for noisy in ("node_modules", ".venv", "__pycache__", ".git"):
        (workspace_dir / noisy).mkdir()
        (workspace_dir / noisy / "target.txt").write_text("x")
    (workspace_dir / "target.txt").write_text("x")

    result = files.search_files("target", str(workspace_dir), policy)

    assert [Path(match["path"]).parent.name for match in result["matches"]] == [
        workspace_dir.name
    ]


# --- ordinary behaviour still works ---------------------------------------


def test_listing_reports_types(policy: FilesystemPolicy, workspace_dir: Path) -> None:
    (workspace_dir / "src").mkdir()
    (workspace_dir / "README.md").write_text("hi")

    result = files.list_directory(str(workspace_dir), policy)

    types = {entry["name"]: entry["type"] for entry in result["entries"]}
    assert types == {"src": "directory", "README.md": "file"}
    assert result["path"] == str(workspace_dir)


def test_listing_a_missing_directory_fails_cleanly(policy: FilesystemPolicy, workspace_dir: Path) -> None:
    result = files.list_directory(f"{workspace_dir}/nope", policy)

    assert result == {"success": False, "error": "That path does not exist."}


def test_listing_a_file_is_rejected(policy: FilesystemPolicy, workspace_dir: Path) -> None:
    (workspace_dir / "note.md").write_text("hi")

    result = files.list_directory(f"{workspace_dir}/note.md", policy)

    assert result["success"] is False
    assert "not a directory" in result["error"]


def test_reading_a_directory_is_rejected(policy: FilesystemPolicy, workspace_dir: Path) -> None:
    (workspace_dir / "src").mkdir()

    result = files.read_file(f"{workspace_dir}/src", policy)

    assert result["success"] is False
    assert "not a file" in result["error"]


def test_search_needs_a_query(policy: FilesystemPolicy, workspace_dir: Path) -> None:
    result = files.search_files("   ", str(workspace_dir), policy)

    assert result["success"] is False
    assert "query is required" in result["error"]


def test_search_finds_a_nested_file(policy: FilesystemPolicy, workspace_dir: Path) -> None:
    project = workspace_dir / "nexus" / "backend"
    project.mkdir(parents=True)
    (project / "BACKEND_SPEC.md").write_text("spec")

    result = files.search_files("BACKEND_SPEC", str(workspace_dir), policy)

    assert result["count"] == 1
    assert result["matches"][0]["path"] == str(project / "BACKEND_SPEC.md")
    assert result["matches"][0]["type"] == "file"


def test_search_is_case_insensitive(policy: FilesystemPolicy, workspace_dir: Path) -> None:
    (workspace_dir / "ReadMe.md").write_text("x")

    assert files.search_files("readme", str(workspace_dir), policy)["count"] == 1


def test_reading_a_normal_file(policy: FilesystemPolicy, workspace_dir: Path) -> None:
    target = workspace_dir / "README.md"
    target.write_text("# NEXUS\n")

    result = files.read_file(str(target), policy)

    assert result["success"] is True
    assert result["content"] == "# NEXUS\n"
    assert result["size"] == 8
    assert result["path"] == str(target)


# --- sensitive directories inside the home directory ----------------------


def test_the_home_library_is_denied_despite_being_inside_the_root() -> None:
    """~/Library holds Keychains, Mail and app tokens. It is inside $HOME."""
    home = Path.home().resolve()
    at_home = FilesystemPolicy(roots=(home,))

    for denied in (
        "Library",
        "Library/Keychains",
        "Library/Application Support/Google/Chrome",
        "Library/Mail",
    ):
        assert is_allowed_path(home / denied, at_home) is False, denied


def test_a_project_folder_named_library_is_still_readable(
    policy: FilesystemPolicy, workspace_dir: Path
) -> None:
    """The ~/Library denial is anchored to home, not to the name."""
    project_library = workspace_dir / "Library"
    project_library.mkdir()

    assert is_allowed_path(project_library, policy) is True


def test_reading_inside_the_home_library_is_refused() -> None:
    home = Path.home().resolve()
    at_home = FilesystemPolicy(roots=(home,))

    result = files.list_directory(str(home / "Library"), at_home)

    assert result["success"] is False
    assert "outside the allowed workspace" in result["error"]
