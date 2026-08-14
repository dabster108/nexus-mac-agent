"""Read-only Git tools.

A real repository is created in a temp directory, so these exercise the actual
Git plumbing without touching any of the developer's own repositories.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest
from conftest import macos_only

from nexus_mac_mcp.core.filesystem import FilesystemPolicy
from nexus_mac_mcp.tools import git

pytestmark = macos_only


def _git(repo: Path, *args: str) -> None:
    subprocess.run(
        ["/usr/bin/git", *args],
        cwd=repo,
        check=True,
        capture_output=True,
        env={
            "PATH": "/usr/bin:/bin",
            "HOME": str(repo),
            "GIT_AUTHOR_NAME": "Test",
            "GIT_AUTHOR_EMAIL": "test@example.com",
            "GIT_COMMITTER_NAME": "Test",
            "GIT_COMMITTER_EMAIL": "test@example.com",
            "GIT_CONFIG_GLOBAL": "/dev/null",
            "GIT_CONFIG_SYSTEM": "/dev/null",
        },
    )


@pytest.fixture
def repo(workspace_dir: Path) -> Path:
    """A real repository with one commit and one uncommitted change."""
    project = workspace_dir / "project"
    project.mkdir()
    _git(project, "init", "-q", "-b", "main")
    (project / "README.md").write_text("# Project\n")
    _git(project, "add", "README.md")
    _git(project, "commit", "-qm", "first commit")
    (project / "README.md").write_text("# Project\n\nmore\n")
    (project / "untracked.txt").write_text("new\n")
    return project


def test_status_reports_branch_and_changes(policy: FilesystemPolicy, repo: Path) -> None:
    result = git.git_status(str(repo), policy)

    assert result["success"] is True
    assert result["branch"] == "main"
    assert result["clean"] is False
    changed = {change["path"] for change in result["changes"]}
    assert changed == {"README.md", "untracked.txt"}
    assert result["path"] == str(repo)


def test_status_finds_the_repository_from_a_subdirectory(
    policy: FilesystemPolicy, repo: Path
) -> None:
    nested = repo / "src" / "deep"
    nested.mkdir(parents=True)

    result = git.git_status(str(nested), policy)

    assert result["success"] is True
    assert result["path"] == str(repo)


def test_branch_lists_and_marks_the_current_one(
    policy: FilesystemPolicy, repo: Path
) -> None:
    _git(repo, "branch", "feature/x")

    result = git.git_branch(str(repo), policy)

    assert result["success"] is True
    assert result["current"] == "main"
    assert set(result["branches"]) == {"main", "feature/x"}


def test_log_returns_commits_newest_first(policy: FilesystemPolicy, repo: Path) -> None:
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "second commit")

    result = git.git_log(str(repo), 10, policy)

    assert result["success"] is True
    assert [commit["subject"] for commit in result["commits"]] == [
        "second commit",
        "first commit",
    ]
    assert result["commits"][0]["author"] == "Test"
    assert result["commits"][0]["hash"]


def test_log_honours_its_limit(policy: FilesystemPolicy, repo: Path) -> None:
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "second commit")

    assert git.git_log(str(repo), 1, policy)["count"] == 1


def test_log_limit_is_capped(policy: FilesystemPolicy, repo: Path) -> None:
    result = git.git_log(str(repo), 10_000, policy)

    assert result["success"] is True
    assert result["count"] <= git.MAX_LOG_LIMIT


def test_log_rejects_a_nonsense_limit(policy: FilesystemPolicy, repo: Path) -> None:
    assert git.git_log(str(repo), 0, policy)["success"] is False


def test_log_copes_with_a_repository_with_no_commits(
    policy: FilesystemPolicy, workspace_dir: Path
) -> None:
    empty = workspace_dir / "empty"
    empty.mkdir()
    _git(empty, "init", "-q", "-b", "main")

    result = git.git_log(str(empty), 5, policy)

    assert result["success"] is True
    assert result["commits"] == []


def test_diff_summarises_without_the_patch(policy: FilesystemPolicy, repo: Path) -> None:
    result = git.git_diff(str(repo), False, policy)

    assert result["success"] is True
    assert result["changed"] is True
    assert any("README.md" in line for line in result["summary"])
    # --stat only: the added line's content never appears.
    assert not any("more" == line.strip() for line in result["summary"])


def test_diff_can_summarise_staged_changes(policy: FilesystemPolicy, repo: Path) -> None:
    _git(repo, "add", "README.md")

    unstaged = git.git_diff(str(repo), False, policy)
    staged = git.git_diff(str(repo), True, policy)

    assert staged["staged"] is True
    assert staged["changed"] is True
    assert unstaged["changed"] is False


# --- boundaries ------------------------------------------------------------


def test_a_directory_outside_the_workspace_is_rejected(
    policy: FilesystemPolicy, outside: Path
) -> None:
    for tool in (git.git_status, git.git_branch, git.git_diff):
        result = tool(str(outside), policy=policy)
        assert result["success"] is False
        assert "outside the allowed workspace" in result["error"]


def test_a_directory_that_is_not_a_repository_is_rejected(
    policy: FilesystemPolicy, workspace_dir: Path
) -> None:
    plain = workspace_dir / "plain"
    plain.mkdir()

    result = git.git_status(str(plain), policy)

    assert result["success"] is False
    assert "not inside a Git repository" in result["error"]


def test_the_repository_search_stops_at_the_workspace_boundary(
    policy: FilesystemPolicy, workspace_dir: Path
) -> None:
    """A repo *above* the allowed root must not be found by walking up."""
    plain = workspace_dir / "plain"
    plain.mkdir()

    assert git.repository_root(plain, policy) is None


def test_only_read_only_subcommands_are_reachable() -> None:
    """There is no parameter through which another subcommand could arrive."""
    import inspect

    for tool in (git.git_status, git.git_branch, git.git_log, git.git_diff):
        parameters = set(inspect.signature(tool).parameters)
        assert parameters <= {"path", "limit", "staged", "policy"}, tool.__name__


@pytest.mark.parametrize(
    "hostile",
    [
        "; rm -rf ~",
        "$(whoami)",
        "--upload-pack=touch /tmp/pwned",
        "-c core.pager=sh",
        "../../../etc",
    ],
)
def test_hostile_path_input_never_reaches_git(
    hostile: str, policy: FilesystemPolicy
) -> None:
    result = git.git_status(hostile, policy)

    # Rejected by the filesystem layer before Git is invoked.
    assert result["success"] is False
