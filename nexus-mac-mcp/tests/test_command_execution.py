"""Running commands: limits, timeouts, cleanup and the environment.

These spawn real processes, but only `python3` running scripts written into a
temp workspace. Nothing here touches the developer's projects.
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path

import pytest
from conftest import macos_only

from nexus_mac_mcp.core.environment import build_environment, describe_environment
from nexus_mac_mcp.core.filesystem import FilesystemPolicy
from nexus_mac_mcp.tools import commands

pytestmark = macos_only


def write(directory: Path, name: str, body: str) -> None:
    (directory / name).write_text(body)


# --- happy path ------------------------------------------------------------


def test_a_successful_command(policy: FilesystemPolicy, workspace_dir: Path) -> None:
    write(workspace_dir, "hello.py", "print('hello from nexus')")

    result = commands.run_command("python3 hello.py", str(workspace_dir), policy)

    assert result["success"] is True
    assert result["status"] == "completed"
    assert result["exit_code"] == 0
    assert "hello from nexus" in result["stdout"]
    assert result["truncated"] is False
    assert result["working_directory"] == str(workspace_dir)
    assert result["command"] == "python3 hello.py"


def test_a_non_zero_exit_code_is_reported(
    policy: FilesystemPolicy, workspace_dir: Path
) -> None:
    write(workspace_dir, "fail.py", "import sys; sys.stderr.write('boom'); sys.exit(3)")

    result = commands.run_command("python3 fail.py", str(workspace_dir), policy)

    assert result["success"] is False
    assert result["status"] == "failed"
    assert result["exit_code"] == 3
    assert "boom" in result["stderr"]


def test_a_missing_executable_is_reported(
    policy: FilesystemPolicy, workspace_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("NEXUS_MAC_COMMAND_PATH", "/nonexistent-bin")

    result = commands.run_command("pytest", str(workspace_dir), policy)

    assert result["success"] is False
    assert result["status"] == "unavailable"


# --- output limits ---------------------------------------------------------


def test_stdout_is_capped(
    policy: FilesystemPolicy, workspace_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("NEXUS_MAC_MAX_OUTPUT_BYTES", "500")
    write(workspace_dir, "flood.py", "print('x' * 200000)")

    result = commands.run_command("python3 flood.py", str(workspace_dir), policy)

    assert result["truncated"] is True
    assert len(result["stdout"]) <= 500
    # The process still finished rather than blocking on a full pipe.
    assert result["exit_code"] == 0


def test_stderr_is_capped(
    policy: FilesystemPolicy, workspace_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("NEXUS_MAC_MAX_OUTPUT_BYTES", "500")
    write(workspace_dir, "noise.py", "import sys; sys.stderr.write('e' * 200000)")

    result = commands.run_command("python3 noise.py", str(workspace_dir), policy)

    assert result["truncated"] is True
    assert len(result["stderr"]) <= 500


# --- timeout and cleanup ---------------------------------------------------


def test_a_hanging_command_times_out(
    policy: FilesystemPolicy, workspace_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("NEXUS_MAC_COMMAND_TIMEOUT", "1")
    write(workspace_dir, "hang.py", "import time; time.sleep(60)")

    started = time.perf_counter()
    result = commands.run_command("python3 hang.py", str(workspace_dir), policy)
    elapsed = time.perf_counter() - started

    assert result["success"] is False
    assert result["status"] == "timeout"
    assert result["exit_code"] is None
    assert "did not finish" in result["error"]
    assert elapsed < 20  # terminated, not waited out


def test_a_timeout_kills_the_whole_process_group(
    policy: FilesystemPolicy, workspace_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A command's children must not outlive it."""
    monkeypatch.setenv("NEXUS_MAC_COMMAND_TIMEOUT", "2")
    write(
        workspace_dir,
        "spawn.py",
        "import subprocess, sys, time, pathlib\n"
        "child = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)'])\n"
        "pathlib.Path('child.pid').write_text(str(child.pid))\n"
        "sys.stdout.flush()\n"
        "time.sleep(60)\n",
    )

    result = commands.run_command("python3 spawn.py", str(workspace_dir), policy)

    assert result["status"] == "timeout"
    child_pid = int((workspace_dir / "child.pid").read_text())
    time.sleep(0.5)

    with pytest.raises(ProcessLookupError):
        # Signal 0 only checks for existence; the child should be gone.
        os.kill(child_pid, 0)


# --- long-running commands -------------------------------------------------


def test_a_long_running_command_is_refused_rather_than_hanging(
    policy: FilesystemPolicy, workspace_dir: Path
) -> None:
    result = commands.run_command("npm run dev", str(workspace_dir), policy)

    assert result["success"] is False
    assert result["status"] == "unsupported"
    # Pointed at the tool that does supervise it, rather than a dead end.
    assert "start_process" in result["error"]


# --- working directory confinement ----------------------------------------


@pytest.mark.parametrize("directory", ["/etc", "/System", "/"])
def test_a_working_directory_outside_the_root_is_refused(
    directory: str, policy: FilesystemPolicy
) -> None:
    result = commands.run_command("pytest", directory, policy)

    assert result["success"] is False
    assert "outside the allowed workspace" in result["error"]


def test_a_traversing_working_directory_is_refused(
    policy: FilesystemPolicy, workspace_dir: Path
) -> None:
    result = commands.run_command("pytest", f"{workspace_dir}/../../..", policy)

    assert result["success"] is False
    assert "outside the allowed workspace" in result["error"]


def test_a_symlinked_working_directory_out_of_the_root_is_refused(
    policy: FilesystemPolicy, workspace_dir: Path, outside: Path
) -> None:
    (workspace_dir / "escape").symlink_to(outside)

    result = commands.run_command("pytest", f"{workspace_dir}/escape", policy)

    assert result["success"] is False
    assert "outside the allowed workspace" in result["error"]


def test_a_missing_working_directory_is_refused(
    policy: FilesystemPolicy, workspace_dir: Path
) -> None:
    result = commands.run_command("pytest", f"{workspace_dir}/nope", policy)

    assert result["success"] is False
    assert "does not exist" in result["error"]


def test_the_command_really_runs_in_the_given_directory(
    policy: FilesystemPolicy, workspace_dir: Path
) -> None:
    nested = workspace_dir / "sub"
    nested.mkdir()
    write(nested, "where.py", "import os; print(os.getcwd())")

    result = commands.run_command("python3 where.py", str(nested), policy)

    assert result["stdout"].strip() == str(nested)


# --- a refused command never starts a process ------------------------------


@pytest.mark.parametrize(
    "command", ["rm -rf /", "pytest && rm -rf /", "sudo reboot", "git push", "npx evil"]
)
def test_a_refused_command_is_rejected_before_execution(
    command: str, policy: FilesystemPolicy, workspace_dir: Path, monkeypatch
) -> None:
    def explode(*args, **kwargs):  # pragma: no cover - must never be reached
        raise AssertionError(f"a process was started for {command!r}")

    monkeypatch.setattr("nexus_mac_mcp.tools.commands.subprocess.Popen", explode)

    result = commands.run_command(command, str(workspace_dir), policy)

    assert result["success"] is False
    assert result["status"] == "rejected"


def test_policy_runs_before_the_working_directory_check(
    policy: FilesystemPolicy,
) -> None:
    """A dangerous command is refused even with a nonsense directory."""
    result = commands.run_command("rm -rf /", "/etc", policy)

    assert "not an allowed command" in result["error"]


# --- environment policy ----------------------------------------------------


def test_the_environment_carries_no_secrets(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GROQ_API_KEY", "gsk-super-secret")
    monkeypatch.setenv("MISTRAL_API_KEY", "mistral-secret")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "aws-secret")
    monkeypatch.setenv("GITHUB_TOKEN", "ghp-secret")

    environment = build_environment()

    assert "GROQ_API_KEY" not in environment
    assert "MISTRAL_API_KEY" not in environment
    assert "AWS_SECRET_ACCESS_KEY" not in environment
    assert "GITHUB_TOKEN" not in environment
    assert "super-secret" not in json.dumps(environment)


def test_the_environment_is_built_not_inherited() -> None:
    environment = build_environment()

    allowed = set(describe_environment()["inherited"]) | set(
        describe_environment()["forced"]
    ) | {"PATH"}
    assert set(environment) <= allowed


def test_the_path_is_the_controlled_one() -> None:
    assert build_environment()["PATH"] == ":".join(describe_environment()["path"])


def test_a_command_cannot_see_the_backends_secrets(
    policy: FilesystemPolicy, workspace_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """End to end: a real process, and the key is genuinely absent."""
    monkeypatch.setenv("GROQ_API_KEY", "gsk-super-secret")
    write(
        workspace_dir,
        "leak.py",
        "import os, json; print(json.dumps(sorted(os.environ)))",
    )

    result = commands.run_command("python3 leak.py", str(workspace_dir), policy)

    seen = json.loads(result["stdout"])
    assert "GROQ_API_KEY" not in seen
    assert "gsk-super-secret" not in result["stdout"]
    assert "HOME" in seen  # but the useful ones are there
