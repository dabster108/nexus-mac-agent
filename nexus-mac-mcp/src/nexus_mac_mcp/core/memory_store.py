"""The persistent memory store.

A small local SQLite database at ``~/.nexus/nexus.db`` — outside any project
workspace, so it survives switching between projects and is never mistaken for
project data. Every write goes through :func:`assert_no_secret` first; nothing
bypasses it, because this module is the only thing that touches the database.

Deletes are soft (``status`` flips to ``DELETED``) so there is an audit trail;
staleness is never stored — it is computed fresh on every read against the
current filesystem, which is the only way it can't itself go stale.
"""

from __future__ import annotations

import json
import os
import sqlite3
import threading
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from nexus_mac_mcp.core.memory_secrets import assert_no_secret
from nexus_mac_mcp.core.memory_types import (
    DEFAULT_CONFIDENCE,
    Memory,
    MemorySource,
    MemoryStatus,
    MemoryType,
    new_memory_id,
)


def _now() -> str:
    return datetime.now(UTC).isoformat()

DEFAULT_DB_DIR = Path.home() / ".nexus"
DEFAULT_DB_NAME = "nexus.db"

MAX_LIST_LIMIT = 50
DEFAULT_LIST_LIMIT = 20

_SCHEMA = """
CREATE TABLE IF NOT EXISTS memories (
    id TEXT PRIMARY KEY,
    type TEXT NOT NULL,
    key TEXT NOT NULL,
    value_json TEXT NOT NULL,
    source TEXT NOT NULL,
    confidence REAL NOT NULL,
    status TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_memories_type_key
    ON memories(type, key)
    WHERE status != 'DELETED';
CREATE INDEX IF NOT EXISTS idx_memories_status ON memories(status);
"""


class MemoryError(Exception):
    """A memory operation was refused. The message is safe to show the agent."""


def default_db_path() -> Path:
    """``~/.nexus/nexus.db``, overridable with ``NEXUS_MAC_DB_PATH`` (tests)."""
    override = os.getenv("NEXUS_MAC_DB_PATH", "").strip()
    if override:
        return Path(override).expanduser()
    return DEFAULT_DB_DIR / DEFAULT_DB_NAME


def _row_to_memory(row: sqlite3.Row) -> Memory:
    return Memory(
        id=row["id"],
        type=MemoryType(row["type"]),
        key=row["key"],
        value=json.loads(row["value_json"]),
        source=MemorySource(row["source"]),
        confidence=row["confidence"],
        status=MemoryStatus(row["status"]),
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


def _is_stale(memory: Memory) -> bool:
    """A WORKSPACE/PROJECT memory naming a path that no longer exists."""
    path = memory.value.get("path") if isinstance(memory.value, dict) else None
    if not path or not isinstance(path, str):
        return False
    try:
        return not Path(path).expanduser().exists()
    except OSError:  # pragma: no cover - defensive
        return False


class MemoryStore:
    """The only code in the process allowed to touch ``nexus.db``."""

    def __init__(self, db_path: Path | None = None) -> None:
        self._path = db_path or default_db_path()
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        with self._connect() as conn:
            conn.executescript(_SCHEMA)

    @contextmanager
    def _connect(self):
        conn = sqlite3.connect(self._path)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    # --- writes --------------------------------------------------------

    def create(
        self,
        *,
        type: MemoryType,
        key: str,
        value: dict[str, Any],
        source: MemorySource,
        confidence: float | None = None,
    ) -> Memory:
        """Insert or replace the (type, key) pair. Refuses anything secret-shaped."""
        key = key.strip()
        if not key:
            raise MemoryError("A memory needs a key.")
        if not isinstance(value, dict):
            raise MemoryError("A memory's value must be an object.")
        assert_no_secret(key, value)

        memory = Memory(
            id=new_memory_id(),
            type=type,
            key=key,
            value=value,
            source=source,
            confidence=confidence if confidence is not None else DEFAULT_CONFIDENCE[source],
        )
        with self._lock, self._connect() as conn:
            # Same (type, key) already ACTIVE: this is an update, not a new memory.
            existing = conn.execute(
                "SELECT id FROM memories WHERE type = ? AND key = ? AND status != 'DELETED'",
                (str(type), key),
            ).fetchone()
            if existing:
                conn.execute(
                    "UPDATE memories SET value_json=?, source=?, confidence=?, "
                    "status='ACTIVE', updated_at=? WHERE id=?",
                    (json.dumps(value), str(source), memory.confidence, memory.updated_at, existing["id"]),
                )
                memory = Memory(
                    id=existing["id"], type=type, key=key, value=value, source=source,
                    confidence=memory.confidence, status=MemoryStatus.ACTIVE,
                    created_at=memory.created_at, updated_at=memory.updated_at,
                )
            else:
                conn.execute(
                    "INSERT INTO memories (id, type, key, value_json, source, confidence, "
                    "status, created_at, updated_at) VALUES (?,?,?,?,?,?,?,?,?)",
                    (
                        memory.id, str(type), key, json.dumps(value), str(source),
                        memory.confidence, str(MemoryStatus.ACTIVE),
                        memory.created_at, memory.updated_at,
                    ),
                )
        return memory

    def delete(
        self,
        *,
        memory_id: str | None = None,
        key: str | None = None,
        type: MemoryType | None = None,
        key_contains: str | None = None,
        wipe_all: bool = False,
    ) -> list[Memory]:
        """Soft-delete matching ACTIVE memories. Returns what was deleted."""
        matches = self._match_for_delete(
            memory_id=memory_id, key=key, type=type, key_contains=key_contains, wipe_all=wipe_all
        )
        if not matches:
            return []
        with self._lock, self._connect() as conn:
            now = _now()
            conn.executemany(
                "UPDATE memories SET status='DELETED', updated_at=? WHERE id=?",
                [(now, memory.id) for memory in matches],
            )
        return matches

    def _match_for_delete(
        self, *, memory_id, key, type, key_contains, wipe_all
    ) -> list[Memory]:
        modes = [memory_id is not None, key is not None, bool(type or key_contains), wipe_all]
        if sum(modes) == 0:
            raise MemoryError(
                "At least one filter is required (memory_id, key, type/key_contains, or wipe_all)."
            )
        if memory_id is not None:
            found = self.get(memory_id=memory_id)
            return [found] if found else []
        if key is not None:
            found = self.get(key=key, type=type)
            return [found] if found else []
        # type/key_contains or wipe_all: bulk.
        return self.list(type=type, query=key_contains, limit=MAX_LIST_LIMIT, include_stale=True)

    # --- reads -----------------------------------------------------------

    def get(
        self, *, memory_id: str | None = None, key: str | None = None, type: MemoryType | None = None
    ) -> Memory | None:
        if not memory_id and not key:
            raise MemoryError("Provide either memory_id or key.")
        with self._connect() as conn:
            if memory_id:
                row = conn.execute(
                    "SELECT * FROM memories WHERE id = ? AND status != 'DELETED'", (memory_id,)
                ).fetchone()
            else:
                clauses = ["key = ?", "status != 'DELETED'"]
                params: list[Any] = [key]
                if type:
                    clauses.insert(1, "type = ?")
                    params.insert(1, str(type))
                row = conn.execute(
                    f"SELECT * FROM memories WHERE {' AND '.join(clauses)}", params
                ).fetchone()
        return _row_to_memory(row) if row else None

    def list(
        self,
        *,
        type: MemoryType | None = None,
        query: str | None = None,
        limit: int = DEFAULT_LIST_LIMIT,
        include_stale: bool = True,
    ) -> list[Memory]:
        """Deterministic search: exact type, then a case-insensitive substring
        match against the key and the JSON value — no embeddings (§16)."""
        limit = max(1, min(limit, MAX_LIST_LIMIT))
        clauses = ["status != 'DELETED'"]
        params: list[Any] = []
        if type:
            clauses.append("type = ?")
            params.append(str(type))
        if query:
            needle = f"%{query.strip().casefold()}%"
            clauses.append("(LOWER(key) LIKE ? OR LOWER(value_json) LIKE ?)")
            params.extend([needle, needle])
        sql = (
            f"SELECT * FROM memories WHERE {' AND '.join(clauses)} "
            f"ORDER BY updated_at DESC LIMIT ?"
        )
        params.append(limit)
        with self._connect() as conn:
            rows = conn.execute(sql, params).fetchall()
        memories = [_row_to_memory(row) for row in rows]
        if not include_stale:
            memories = [memory for memory in memories if not _is_stale(memory)]
        return memories

    @staticmethod
    def is_stale(memory: Memory) -> bool:
        return _is_stale(memory)
