"""Shared fixtures.

Unit tests never touch the real machine: ``run`` is replaced with canned
output. The tests that do read this Mac are the read-only ones, and anything
that would launch an application is marked ``integration``.
"""

from __future__ import annotations

import sys
from collections.abc import Callable
from pathlib import Path

import pytest

from nexus_mac_mcp.core.filesystem import FilesystemPolicy
from nexus_mac_mcp.core.platform import CommandResult

macos_only = pytest.mark.skipif(
    sys.platform != "darwin", reason="requires macOS"
)


@pytest.fixture
def fake_run(monkeypatch: pytest.MonkeyPatch) -> Callable[..., list[list[str]]]:
    """Replace ``run`` in a tool module with a canned result or error.

    Returns the list the calls are recorded into, so a test can assert exactly
    what argv would have been executed.
    """

    def install(module: object, stdout: str = "", error: Exception | None = None):
        calls: list[list[str]] = []

        def _run(argv: list[str], timeout: float = 5.0) -> CommandResult:
            calls.append(argv)
            if error is not None:
                raise error
            return CommandResult(stdout=stdout, stderr="")

        monkeypatch.setattr(module, "run", _run)
        return calls

    return install


@pytest.fixture
def workspace_dir(tmp_path: Path) -> Path:
    """An allowed workspace root, resolved (macOS temp dirs are symlinked)."""
    root = tmp_path / "workspace"
    root.mkdir()
    return root.resolve()


@pytest.fixture
def outside(tmp_path: Path) -> Path:
    """A directory deliberately *not* inside the workspace."""
    other = tmp_path / "outside"
    other.mkdir()
    (other / "secret.txt").write_text("you should not see this")
    return other.resolve()


@pytest.fixture
def policy(workspace_dir: Path) -> FilesystemPolicy:
    """A policy confined to the test workspace, with small limits."""
    return FilesystemPolicy(
        roots=(workspace_dir,),
        max_file_bytes=1024,
        max_entries=5,
        max_matches=3,
        max_depth=3,
    )


@pytest.fixture
def memory_store(tmp_path: Path) -> "MemoryStore":
    """A fresh SQLite-backed store, never the real ~/.nexus/nexus.db."""
    from nexus_mac_mcp.core.memory_store import MemoryStore

    return MemoryStore(tmp_path / "test-nexus.db")


@pytest.fixture
def app_dir(tmp_path: Path) -> Path:
    """A directory of fake ``.app`` bundles."""
    for name in (
        "Visual Studio Code.app",
        "Safari.app",
        "Finder.app",
        "Microsoft Word.app",
        "Microsoft Excel.app",
        "not-an-app.txt",
    ):
        target = tmp_path / name
        if name.endswith(".app"):
            target.mkdir()
        else:
            target.write_text("")
    return tmp_path
