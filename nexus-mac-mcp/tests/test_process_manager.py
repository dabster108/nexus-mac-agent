"""Process lifecycle, logs, cleanup and the security boundary.

Real processes are spawned, but only short-lived `python3` scripts in a temp
workspace. Nothing here starts a development server on the developer's machine.
"""

from __future__ import annotations

import os
import socket
import time
from pathlib import Path

import pytest
from conftest import macos_only

from nexus_mac_mcp.core.filesystem import FilesystemPolicy
from nexus_mac_mcp.core.process_manager import (
    MAX_LOG_BYTES,
    ProcessError,
    ProcessManager,
    ProcessStatus,
    RingBuffer,
    port_is_free,
)
from nexus_mac_mcp.tools import processes

pytestmark = macos_only


@pytest.fixture
def manager() -> ProcessManager:
    made = ProcessManager()
    yield made
    made.shutdown_all()


def script(directory: Path, name: str, body: str) -> str:
    (directory / name).write_text(body)
    return name


def wait_for(predicate, timeout: float = 5.0) -> bool:
    deadline = time.perf_counter() + timeout
    while time.perf_counter() < deadline:
        if predicate():
            return True
        time.sleep(0.05)
    return False


# --- ring buffer -----------------------------------------------------------


def test_the_ring_buffer_keeps_the_most_recent_bytes() -> None:
    buffer = RingBuffer(limit=100)

    buffer.write(b"old" * 50)
    buffer.write(b"recent")

    text = buffer.text()
    assert text.endswith("recent")
    assert len(text) <= 100
    assert buffer.dropped is True


def test_the_ring_buffer_reports_no_loss_when_small() -> None:
    buffer = RingBuffer(limit=1000)
    buffer.write(b"hello")

    assert buffer.text() == "hello"
    assert buffer.dropped is False


def test_the_ring_buffer_can_return_recent_lines() -> None:
    buffer = RingBuffer()
    buffer.write(b"\n".join(f"line {i}".encode() for i in range(50)))

    assert buffer.text(lines=3).splitlines() == ["line 47", "line 48", "line 49"]


def test_the_default_buffer_is_bounded() -> None:
    assert MAX_LOG_BYTES == 200_000


# --- lifecycle -------------------------------------------------------------


def test_a_process_reaches_running(manager: ProcessManager, workspace_dir: Path) -> None:
    script(workspace_dir, "server.py", "import time; time.sleep(30)")

    record = manager.start(
        command="python3 server.py",
        argv=["python3", "server.py"],
        working_directory=workspace_dir,
    )

    assert record.status is ProcessStatus.RUNNING
    assert record.pid is not None
    assert record.process_id.startswith("proc_")
    assert record.runtime_seconds >= 0


def test_a_process_that_exits_cleanly_becomes_stopped(
    manager: ProcessManager, workspace_dir: Path
) -> None:
    script(workspace_dir, "quick.py", "print('done')")

    record = manager.start(
        command="python3 quick.py",
        argv=["python3", "quick.py"],
        working_directory=workspace_dir,
    )

    assert wait_for(lambda: manager.get(record.process_id).status is ProcessStatus.STOPPED)
    assert manager.get(record.process_id).exit_code == 0


def test_a_process_that_crashes_becomes_failed(
    manager: ProcessManager, workspace_dir: Path
) -> None:
    script(workspace_dir, "crash.py", "import sys; sys.stderr.write('bad'); sys.exit(2)")

    record = manager.start(
        command="python3 crash.py",
        argv=["python3", "crash.py"],
        working_directory=workspace_dir,
    )

    assert wait_for(lambda: manager.get(record.process_id).status is ProcessStatus.FAILED)
    refreshed = manager.get(record.process_id)
    assert refreshed.exit_code == 2
    assert "bad" in refreshed.logs()["stderr"]


def test_stopping_a_process(manager: ProcessManager, workspace_dir: Path) -> None:
    script(workspace_dir, "server.py", "import time; time.sleep(60)")
    record = manager.start(
        command="python3 server.py",
        argv=["python3", "server.py"],
        working_directory=workspace_dir,
    )
    pid = record.pid

    stopped = manager.stop(record.process_id)

    assert stopped.status is ProcessStatus.STOPPED
    assert stopped.stopped_at is not None
    time.sleep(0.3)
    with pytest.raises(ProcessLookupError):
        os.kill(pid, 0)


def test_stopping_takes_the_children_too(
    manager: ProcessManager, workspace_dir: Path
) -> None:
    """A dev server's workers must not survive it."""
    script(
        workspace_dir,
        "parent.py",
        "import subprocess, sys, pathlib, time\n"
        "child = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)'])\n"
        "pathlib.Path('child.pid').write_text(str(child.pid))\n"
        "time.sleep(60)\n",
    )
    record = manager.start(
        command="python3 parent.py",
        argv=["python3", "parent.py"],
        working_directory=workspace_dir,
    )
    assert wait_for(lambda: (workspace_dir / "child.pid").exists())
    child_pid = int((workspace_dir / "child.pid").read_text())

    manager.stop(record.process_id)
    time.sleep(0.5)

    with pytest.raises(ProcessLookupError):
        os.kill(child_pid, 0)


def test_stopping_an_already_stopped_process_is_an_error(
    manager: ProcessManager, workspace_dir: Path
) -> None:
    script(workspace_dir, "quick.py", "print('done')")
    record = manager.start(
        command="python3 quick.py",
        argv=["python3", "quick.py"],
        working_directory=workspace_dir,
    )
    assert wait_for(lambda: manager.get(record.process_id).status is ProcessStatus.STOPPED)

    with pytest.raises(ProcessError, match="already"):
        manager.stop(record.process_id)


def test_shutdown_stops_everything(manager: ProcessManager, workspace_dir: Path) -> None:
    script(workspace_dir, "server.py", "import time; time.sleep(60)")
    records = [
        manager.start(
            command="python3 server.py",
            argv=["python3", "server.py"],
            working_directory=workspace_dir,
        )
        for _ in range(2)
    ]

    stopped = manager.shutdown_all()

    assert len(stopped) == 2
    time.sleep(0.3)
    for record in records:
        with pytest.raises(ProcessLookupError):
            os.kill(record.pid, 0)


def test_too_many_processes_is_refused(
    manager: ProcessManager, workspace_dir: Path
) -> None:
    small = ProcessManager(max_processes=1)
    script(workspace_dir, "server.py", "import time; time.sleep(30)")
    small.start(
        command="python3 server.py",
        argv=["python3", "server.py"],
        working_directory=workspace_dir,
    )
    try:
        with pytest.raises(ProcessError, match="Too many processes"):
            small.start(
                command="python3 server.py",
                argv=["python3", "server.py"],
                working_directory=workspace_dir,
            )
    finally:
        small.shutdown_all()


# --- ports -----------------------------------------------------------------


def test_an_occupied_port_is_reported_not_cleared(
    manager: ProcessManager, workspace_dir: Path
) -> None:
    """NEXUS must never kill whatever already holds a port."""
    holder = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    holder.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    holder.bind(("127.0.0.1", 0))
    holder.listen(1)
    port = holder.getsockname()[1]
    script(workspace_dir, "server.py", "import time; time.sleep(30)")

    try:
        with pytest.raises(ProcessError, match=f"Port {port} is already in use"):
            manager.start(
                command="fake server",
                argv=["python3", "server.py"],
                working_directory=workspace_dir,
                host="127.0.0.1",
                port=port,
            )
        # The holder is untouched.
        assert holder.fileno() != -1
    finally:
        holder.close()


def test_a_free_port_is_detected() -> None:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.bind(("127.0.0.1", 0))
        taken = probe.getsockname()[1]
        assert port_is_free("127.0.0.1", taken) is False


# --- the security boundary -------------------------------------------------


def test_an_unknown_process_cannot_be_addressed(manager: ProcessManager) -> None:
    for action in (manager.get, manager.stop):
        with pytest.raises(ProcessError, match="Unknown process"):
            action("proc_does_not_exist")


def test_a_raw_pid_cannot_be_stopped(manager: ProcessManager) -> None:
    """Only ids this manager issued are addressable — never a pid."""
    with pytest.raises(ProcessError, match="Unknown process"):
        manager.stop(str(os.getpid()))
    # This process is obviously still alive.
    os.kill(os.getpid(), 0)


def test_only_managed_processes_are_listed(
    manager: ProcessManager, workspace_dir: Path
) -> None:
    script(workspace_dir, "server.py", "import time; time.sleep(30)")
    manager.start(
        command="python3 server.py",
        argv=["python3", "server.py"],
        working_directory=workspace_dir,
    )

    listed = manager.list()

    assert len(listed) == 1  # not the machine's process table
    assert listed[0].command == "python3 server.py"


# --- the tool layer --------------------------------------------------------


def test_start_process_refuses_a_short_lived_command(
    policy: FilesystemPolicy, workspace_dir: Path, manager: ProcessManager
) -> None:
    result = processes.start_process("pytest", str(workspace_dir), policy, manager)

    assert result["success"] is False
    assert "run_command" in result["error"]


def test_start_process_refuses_a_dangerous_command(
    policy: FilesystemPolicy, workspace_dir: Path, manager: ProcessManager
) -> None:
    for command in ("rm -rf /", "npm run dev && rm -rf /", "sudo reboot"):
        result = processes.start_process(command, str(workspace_dir), policy, manager)
        assert result["success"] is False


def test_start_process_refuses_public_binding(
    policy: FilesystemPolicy, workspace_dir: Path, manager: ProcessManager
) -> None:
    result = processes.start_process(
        "uvicorn app.main:app --host 0.0.0.0", str(workspace_dir), policy, manager
    )

    assert result["success"] is False
    assert manager.list() == []


@pytest.mark.parametrize("directory", ["/etc", "/System"])
def test_start_process_refuses_a_working_directory_outside_the_root(
    directory: str, policy: FilesystemPolicy, manager: ProcessManager
) -> None:
    result = processes.start_process("npm run dev", directory, policy, manager)

    assert result["success"] is False
    assert "outside the allowed workspace" in result["error"]


def test_start_process_refuses_a_symlinked_escape(
    policy: FilesystemPolicy, workspace_dir: Path, outside: Path, manager: ProcessManager
) -> None:
    (workspace_dir / "escape").symlink_to(outside)

    result = processes.start_process(
        "npm run dev", f"{workspace_dir}/escape", policy, manager
    )

    assert result["success"] is False
    assert "outside the allowed workspace" in result["error"]


def test_the_tools_report_status_and_logs(
    manager: ProcessManager, workspace_dir: Path
) -> None:
    script(workspace_dir, "chatty.py", "print('listening on 3000'); import time; time.sleep(30)")
    record = manager.start(
        command="python3 chatty.py",
        argv=["python3", "chatty.py"],
        working_directory=workspace_dir,
        host="127.0.0.1",
        port=3000,
    )

    listed = processes.list_processes(manager)
    assert listed["count"] == 1
    assert listed["processes"][0]["url"] == "http://127.0.0.1:3000"

    status = processes.process_status(record.process_id, manager)
    assert status["status"] == "RUNNING"
    assert status["exit_code"] is None

    assert wait_for(
        lambda: "listening" in processes.process_logs(record.process_id, 10, manager)["stdout"]
    )
    logs = processes.process_logs(record.process_id, 10, manager)
    assert logs["truncated"] is False

    stopped = processes.stop_process(record.process_id, manager)
    assert stopped["status"] == "STOPPED"


def test_the_tools_report_unknown_ids_cleanly(manager: ProcessManager) -> None:
    for result in (
        processes.process_status("proc_nope", manager),
        processes.process_logs("proc_nope", 10, manager),
        processes.stop_process("proc_nope", manager),
    ):
        assert result["success"] is False
        assert "Unknown process" in result["error"]


def test_log_lines_must_be_positive(manager: ProcessManager) -> None:
    assert processes.process_logs("proc_x", 0, manager)["success"] is False
