"""Supervision of long-running development processes.

A managed process is one NEXUS started and still knows about. That is the whole
security model for stopping things: :meth:`ProcessManager.stop` takes a
``process_id`` this manager issued, never a pid, so there is no way to ask it to
signal something it did not start.

Each process gets its own process group, so stopping a dev server takes its
workers with it rather than orphaning them. Output is held in ring buffers —
a server that logs for a week must not grow without bound.

Nothing here decides *what* may run; :mod:`nexus_mac_mcp.core.process_policy`
does, and it defers to the ordinary command policy for the actual command.
"""

from __future__ import annotations

import atexit
import errno
import os
import signal
import socket
import subprocess
import threading
import time
from collections import deque
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from typing import IO, Any
from uuid import uuid4

from nexus_mac_mcp.core.environment import build_environment, resolve_executable

#: Per stream, per process.
MAX_LOG_BYTES = 200_000
DEFAULT_LOG_LINES = 100
MAX_LOG_LINES = 1000
#: A cap on how much can be running at once, so a confused agent cannot fill
#: the machine with dev servers.
MAX_PROCESSES = 8
#: How long to wait after spawning before deciding the process is up.
STARTUP_SETTLE_SECONDS = 0.4
#: Grace between SIGTERM and SIGKILL.
STOP_GRACE_SECONDS = 5.0


class ProcessStatus(StrEnum):
    STARTING = "STARTING"
    RUNNING = "RUNNING"
    STOPPING = "STOPPING"
    STOPPED = "STOPPED"
    FAILED = "FAILED"

    @property
    def is_active(self) -> bool:
        return self in (ProcessStatus.STARTING, ProcessStatus.RUNNING, ProcessStatus.STOPPING)


class ProcessError(Exception):
    """A process operation failed. The message is safe to show the agent."""


def new_process_id() -> str:
    return f"proc_{uuid4().hex[:12]}"


def _now() -> str:
    return datetime.now(UTC).isoformat()


class RingBuffer:
    """Keeps the most recent ``limit`` bytes and forgets the rest."""

    def __init__(self, limit: int = MAX_LOG_BYTES) -> None:
        self._chunks: deque[bytes] = deque()
        self._limit = limit
        self._size = 0
        self._dropped = 0
        self._lock = threading.Lock()

    def write(self, data: bytes) -> None:
        with self._lock:
            self._chunks.append(data)
            self._size += len(data)
            while self._size > self._limit and self._chunks:
                oldest = self._chunks.popleft()
                self._size -= len(oldest)
                self._dropped += len(oldest)

    def text(self, lines: int | None = None) -> str:
        with self._lock:
            raw = b"".join(self._chunks)
        text = raw.decode("utf-8", errors="replace")
        if lines is None:
            return text
        return "\n".join(text.splitlines()[-lines:])

    @property
    def dropped(self) -> bool:
        with self._lock:
            return self._dropped > 0


@dataclass
class ManagedProcess:
    """One supervised process."""

    process_id: str
    command: str
    working_directory: str
    status: ProcessStatus = ProcessStatus.STARTING
    pid: int | None = None
    host: str | None = None
    port: int | None = None
    started_at: str = field(default_factory=_now)
    stopped_at: str | None = None
    exit_code: int | None = None
    label: str = ""
    _popen: subprocess.Popen[bytes] | None = field(default=None, repr=False)
    _stdout: RingBuffer = field(default_factory=RingBuffer, repr=False)
    _stderr: RingBuffer = field(default_factory=RingBuffer, repr=False)
    _readers: list[threading.Thread] = field(default_factory=list, repr=False)

    @property
    def runtime_seconds(self) -> float:
        started = datetime.fromisoformat(self.started_at)
        end = datetime.fromisoformat(self.stopped_at) if self.stopped_at else datetime.now(UTC)
        return round((end - started).total_seconds(), 1)

    def summary(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "process_id": self.process_id,
            "status": str(self.status),
            "command": self.command,
            "working_directory": self.working_directory,
            "pid": self.pid,
            "started_at": self.started_at,
            "runtime_seconds": self.runtime_seconds,
            "exit_code": self.exit_code,
        }
        if self.port is not None:
            payload["port"] = self.port
            payload["host"] = self.host
            payload["url"] = f"http://{self.host}:{self.port}"
        if self.label:
            payload["label"] = self.label
        return payload

    def logs(self, lines: int = DEFAULT_LOG_LINES) -> dict[str, Any]:
        return {
            "process_id": self.process_id,
            "status": str(self.status),
            "stdout": self._stdout.text(lines),
            "stderr": self._stderr.text(lines),
            "truncated": self._stdout.dropped or self._stderr.dropped,
        }


def port_is_free(host: str, port: int) -> bool:
    """Whether nothing is already listening there."""
    family = socket.AF_INET6 if ":" in host else socket.AF_INET
    with socket.socket(family, socket.SOCK_STREAM) as probe:
        probe.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            probe.bind((host, port))
        except OSError as exc:
            return exc.errno not in (errno.EADDRINUSE, errno.EACCES)
    return True


class ProcessManager:
    """Starts, tracks and stops development processes."""

    def __init__(self, max_processes: int = MAX_PROCESSES) -> None:
        self._processes: dict[str, ManagedProcess] = {}
        self._max = max_processes
        self._lock = threading.Lock()

    # --- lifecycle ---------------------------------------------------
    def start(
        self,
        *,
        command: str,
        argv: list[str],
        working_directory: Path,
        host: str | None = None,
        port: int | None = None,
        label: str = "",
    ) -> ManagedProcess:
        """Spawn a process and begin supervising it."""
        self.refresh_all()
        with self._lock:
            active = [p for p in self._processes.values() if p.status.is_active]
            if len(active) >= self._max:
                raise ProcessError(
                    f"Too many processes are already running ({len(active)}). "
                    f"Stop one before starting another."
                )

        if port is not None and not port_is_free(host or "127.0.0.1", port):
            # Deliberately not resolved for the caller: killing whatever holds a
            # port is not a decision this layer gets to make.
            raise ProcessError(
                f"Port {port} is already in use. Stop whatever is using it and try again."
            )

        executable = resolve_executable(argv[0])
        if executable is None:
            raise ProcessError(f"'{argv[0]}' is not installed on this Mac.")

        record = ManagedProcess(
            process_id=new_process_id(),
            command=command,
            working_directory=str(working_directory),
            host=host,
            port=port,
            label=label,
        )
        try:
            popen = subprocess.Popen(  # noqa: S603 - argv list, never a shell
                [executable, *argv[1:]],
                cwd=str(working_directory),
                env=build_environment(),
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                stdin=subprocess.DEVNULL,
                start_new_session=True,  # own process group: children die with it
            )
        except (OSError, ValueError) as exc:
            raise ProcessError(f"That process could not be started: {exc}") from exc

        record._popen = popen
        record.pid = popen.pid
        assert popen.stdout is not None and popen.stderr is not None
        record._readers = [
            self._reader(popen.stdout, record._stdout),
            self._reader(popen.stderr, record._stderr),
        ]

        # Give it a moment to fall over, so an immediate failure is reported as
        # FAILED rather than optimistically as RUNNING.
        time.sleep(STARTUP_SETTLE_SECONDS)
        self._refresh(record)
        if record.status is ProcessStatus.STARTING:
            record.status = ProcessStatus.RUNNING

        with self._lock:
            self._processes[record.process_id] = record
        return record

    @staticmethod
    def _reader(stream: IO[bytes], buffer: RingBuffer) -> threading.Thread:
        def drain() -> None:
            try:
                # read1: a single underlying read, returning whatever is
                # available. `read(n)` would block until n bytes arrived, so a
                # server that logs a line and then waits would appear silent.
                for chunk in iter(lambda: stream.read1(4096), b""):
                    buffer.write(chunk)
            except (OSError, ValueError):  # pipe closed
                return

        thread = threading.Thread(target=drain, daemon=True)
        thread.start()
        return thread

    def stop(self, process_id: str) -> ManagedProcess:
        """Stop a managed process: SIGTERM, then SIGKILL if it does not go."""
        record = self.require(process_id)
        self._refresh(record)
        if not record.status.is_active:
            raise ProcessError(
                f"That process is already {record.status}."
            )

        record.status = ProcessStatus.STOPPING
        popen = record._popen
        if popen is not None:
            _terminate_group(popen)
        self._refresh(record)
        if record.status.is_active:  # pragma: no cover - refused to die
            record.status = ProcessStatus.STOPPED
            record.stopped_at = _now()
        return record

    def shutdown_all(self) -> list[str]:
        """Stop everything still running. Called when the MCP server exits."""
        stopped: list[str] = []
        for record in list(self._processes.values()):
            if record.status.is_active and record._popen is not None:
                _terminate_group(record._popen)
                record.status = ProcessStatus.STOPPED
                record.stopped_at = _now()
                stopped.append(record.process_id)
        return stopped

    # --- inspection --------------------------------------------------
    def require(self, process_id: str) -> ManagedProcess:
        record = self._processes.get(process_id)
        if record is None:
            # Only ids this manager issued are addressable, so an arbitrary pid
            # cannot be reached through any tool.
            raise ProcessError(
                f"Unknown process '{process_id}'. "
                f"Call list_processes to see the processes NEXUS is managing."
            )
        return record

    def get(self, process_id: str) -> ManagedProcess:
        record = self.require(process_id)
        self._refresh(record)
        return record

    def list(self) -> list[ManagedProcess]:
        self.refresh_all()
        return sorted(self._processes.values(), key=lambda p: p.started_at, reverse=True)

    def refresh_all(self) -> None:
        for record in list(self._processes.values()):
            self._refresh(record)

    @staticmethod
    def _refresh(record: ManagedProcess) -> None:
        """Notice a process that has exited on its own."""
        popen = record._popen
        if popen is None or not record.status.is_active:
            return
        code = popen.poll()
        if code is None:
            return
        record.exit_code = code
        record.stopped_at = record.stopped_at or _now()
        if record.status is ProcessStatus.STOPPING:
            # We asked it to exit, so a signal-terminated exit is success.
            record.status = ProcessStatus.STOPPED
        else:
            record.status = ProcessStatus.STOPPED if code == 0 else ProcessStatus.FAILED


def _terminate_group(popen: subprocess.Popen[bytes]) -> None:
    """End the process group: SIGTERM, then SIGKILL if it lingers."""
    try:
        group = os.getpgid(popen.pid)
    except (ProcessLookupError, OSError):
        return
    for sig in (signal.SIGTERM, signal.SIGKILL):
        try:
            os.killpg(group, sig)
        except (ProcessLookupError, PermissionError, OSError):
            return
        try:
            popen.wait(timeout=STOP_GRACE_SECONDS)
            return
        except subprocess.TimeoutExpired:
            continue


_manager = ProcessManager()


def get_process_manager() -> ProcessManager:
    """The process-wide manager."""
    return _manager


def _shutdown() -> None:  # pragma: no cover - exercised by the integration test
    _manager.shutdown_all()


atexit.register(_shutdown)
