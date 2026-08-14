"""Workspace detection."""

from __future__ import annotations

from pathlib import Path

from nexus_mac_mcp.core.filesystem import FilesystemPolicy
from nexus_mac_mcp.tools import workspace


def test_a_python_uv_project_is_recognised(
    policy: FilesystemPolicy, workspace_dir: Path
) -> None:
    (workspace_dir / "pyproject.toml").write_text(
        '[project]\ndependencies = ["fastapi>=0.1", "langgraph"]\n'
    )
    (workspace_dir / "uv.lock").write_text("")

    result = workspace.detect_workspace(str(workspace_dir), policy)

    assert result["success"] is True
    assert set(result["project_types"]) >= {"python", "uv", "fastapi", "langgraph"}
    assert set(result["files"]) == {"pyproject.toml", "uv.lock"}
    assert result["is_project"] is True


def test_a_nextjs_project_is_recognised(
    policy: FilesystemPolicy, workspace_dir: Path
) -> None:
    (workspace_dir / "package.json").write_text(
        '{"dependencies": {"next": "15.0.0", "react": "19.0.0"}}'
    )
    (workspace_dir / "next.config.mjs").write_text("export default {}")

    result = workspace.detect_workspace(str(workspace_dir), policy)

    assert set(result["project_types"]) >= {"node", "nextjs", "react"}


def test_a_git_repository_is_reported(
    policy: FilesystemPolicy, workspace_dir: Path
) -> None:
    (workspace_dir / ".git").mkdir()

    result = workspace.detect_workspace(str(workspace_dir), policy)

    assert result["is_git_repository"] is True
    assert ".git" in result["files"]


def test_a_plain_directory_is_not_a_project(
    policy: FilesystemPolicy, workspace_dir: Path
) -> None:
    (workspace_dir / "holiday.jpg").write_text("x")

    result = workspace.detect_workspace(str(workspace_dir), policy)

    assert result["project_types"] == []
    assert result["is_git_repository"] is False
    assert result["is_project"] is False


def test_detection_runs_no_commands(
    policy: FilesystemPolicy, workspace_dir: Path, monkeypatch
) -> None:
    def explode(*args, **kwargs):  # pragma: no cover - must never be reached
        raise AssertionError("detect_workspace must not execute commands")

    monkeypatch.setattr("nexus_mac_mcp.core.platform.subprocess.run", explode)
    (workspace_dir / "pyproject.toml").write_text("[project]")

    assert workspace.detect_workspace(str(workspace_dir), policy)["success"] is True


def test_detection_is_confined_to_the_workspace(
    policy: FilesystemPolicy, outside: Path
) -> None:
    result = workspace.detect_workspace(str(outside), policy)

    assert result["success"] is False
    assert "outside the allowed workspace" in result["error"]


def test_an_enormous_manifest_is_not_sniffed(
    policy: FilesystemPolicy, workspace_dir: Path
) -> None:
    (workspace_dir / "package.json").write_text('{"x":"' + "a" * 70_000 + '"}')

    result = workspace.detect_workspace(str(workspace_dir), policy)

    # Still detected as node from the marker file, without reading 70KB.
    assert "node" in result["project_types"]
