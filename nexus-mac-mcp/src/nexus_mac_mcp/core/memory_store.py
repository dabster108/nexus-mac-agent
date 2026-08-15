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

#: Ceiling on one memory's serialised value. A memory is a short fact — a path,
#: a port, a preference — so this is generous. The bound matters because the
#: value is read back into the agent's transcript verbatim: without it, one
#: oversized save silently poisons every later request with a prompt too large
#: for the model to accept.
MAX_VALUE_BYTES = 8_192

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

#: Columns added after the table shipped. Applied one at a time and ignored if
#: already present, so an existing ``~/.nexus/nexus.db`` keeps its rows rather
#: than needing a rebuild.
_MIGRATIONS: tuple[tuple[str, str], ...] = (
    ("last_verified_at", "ALTER TABLE memories ADD COLUMN last_verified_at TEXT"),
)


class MemoryError(Exception):
    """A memory operation was refused. The message is safe to show the agent."""


#: Said for every unusable-database condition. Deliberately one fixed string:
#: the underlying errors name the database path and the host's filesystem
#: state, neither of which belongs in a message handed to the model.
_UNAVAILABLE = (
    "The memory database is unavailable, so nothing could be remembered or "
    "recalled. Everything else still works."
)


def default_db_path() -> Path:
    """``~/.nexus/nexus.db``, overridable with ``NEXUS_MAC_DB_PATH`` (tests)."""
    override = os.getenv("NEXUS_MAC_DB_PATH", "").strip()
    if override:
        return Path(override).expanduser()
    return DEFAULT_DB_DIR / DEFAULT_DB_NAME


def _row_to_memory(row: sqlite3.Row) -> Memory:
    keys = row.keys()
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
        last_verified_at=row["last_verified_at"] if "last_verified_at" in keys else None,
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
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            raise MemoryError(_UNAVAILABLE) from exc
        self._lock = threading.Lock()
        with self._connect() as conn:
            conn.executescript(_SCHEMA)
            self._migrate(conn)

    @staticmethod
    def _migrate(conn: sqlite3.Connection) -> None:
        """Bring an older database up to the current shape, in place."""
        existing = {row[1] for row in conn.execute("PRAGMA table_info(memories)")}
        for column, statement in _MIGRATIONS:
            if column not in existing:
                conn.execute(statement)

    @contextmanager
    def _connect(self):
        """The single door to the database, and so the single place its
        failures are translated.

        A corrupt file, a read-only volume or a vanished home directory raises
        ``sqlite3.Error``/``OSError`` from anywhere in this class. Those escape
        as protocol-level tool errors — losing the clean ``success: false``
        shape every other refusal uses — and their text names the database path
        and the host's filesystem state. Both become one safe message here.
        """
        try:
            conn = sqlite3.connect(self._path)
        except (sqlite3.Error, OSError) as exc:
            raise MemoryError(_UNAVAILABLE) from exc
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        except sqlite3.Error as exc:
            raise MemoryError(_UNAVAILABLE) from exc
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
        try:
            encoded = json.dumps(value)
        except (TypeError, ValueError, RecursionError) as exc:
            raise MemoryError("That memory's value could not be stored.") from exc
        if len(encoded.encode("utf-8")) > MAX_VALUE_BYTES:
            raise MemoryError(
                f"That memory is too large to store (limit {MAX_VALUE_BYTES} bytes). "
                "Remember a short fact, such as a path, rather than a document."
            )
        assert_no_secret(key, value)

        memory = Memory(
            id=new_memory_id(),
            type=type,
            key=key,
            value=value,
            source=source,
            confidence=confidence if confidence is not None else DEFAULT_CONFIDENCE[source],
            # Writing a value *is* verifying it: the fact was true just now.
            last_verified_at=_now(),
        )
        with self._lock, self._connect() as conn:
            # Same (type, key) already ACTIVE: this is an update, not a new memory.
            existing = conn.execute(
                "SELECT id FROM memories WHERE type = ? AND key = ? AND status != 'DELETED'",
                (str(type), key),
            ).fetchone()
            if existing:
                # A rewrite revives a memory that live evidence had contradicted:
                # the new value is what the world says now.
                conn.execute(
                    "UPDATE memories SET value_json=?, source=?, confidence=?, "
                    "status='ACTIVE', updated_at=?, last_verified_at=? WHERE id=?",
                    (
                        encoded, str(source), memory.confidence, memory.updated_at,
                        memory.last_verified_at, existing["id"],
                    ),
                )
                memory = Memory(
                    id=existing["id"], type=type, key=key, value=value, source=source,
                    confidence=memory.confidence, status=MemoryStatus.ACTIVE,
                    created_at=memory.created_at, updated_at=memory.updated_at,
                    last_verified_at=memory.last_verified_at,
                )
            else:
                conn.execute(
                    "INSERT INTO memories (id, type, key, value_json, source, confidence, "
                    "status, created_at, updated_at, last_verified_at) "
                    "VALUES (?,?,?,?,?,?,?,?,?,?)",
                    (
                        memory.id, str(type), key, encoded, str(source),
                        memory.confidence, str(MemoryStatus.ACTIVE),
                        memory.created_at, memory.updated_at, memory.last_verified_at,
                    ),
                )
        return memory

    def verify(self, memory_id: str) -> Memory | None:
        """Record that live evidence just agreed with this memory.

        Confidence itself is not raised — being right once does not make a
        memory more true — but the clock that decays it resets, which is what
        keeps a long-lived, regularly-confirmed fact reading as HIGH.
        """
        now = _now()
        with self._lock, self._connect() as conn:
            conn.execute(
                "UPDATE memories SET last_verified_at=? WHERE id=? AND status='ACTIVE'",
                (now, memory_id),
            )
        return self.get(memory_id=memory_id)

    def mark_stale(self, memory_id: str) -> Memory | None:
        """Record that live evidence *contradicted* this memory.

        Path staleness stays computed at read time — a directory can come back,
        and a stored flag would not notice. Being contradicted is different: it
        is a fact about the memory, established once, and the row keeps it so a
        later session does not re-learn the same disagreement. The row is
        retained rather than deleted; the user decides whether to forget it.
        """
        now = _now()
        with self._lock, self._connect() as conn:
            conn.execute(
                "UPDATE memories SET status='STALE', updated_at=? "
                "WHERE id=? AND status='ACTIVE'",
                (now, memory_id),
            )
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM memories WHERE id=? AND status!='DELETED'", (memory_id,)
            ).fetchone()
        return _row_to_memory(row) if row else None

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
        # type/key_contains or wipe_all: bulk. Deliberately *not* self.list() —
        # that caps results at MAX_LIST_LIMIT to keep a prompt small, and a
        # display limit must never become a deletion limit. Borrowing it meant
        # "forget everything" silently left the 51st memory behind while
        # reporting success.
        return self._match_all(type=type, key_contains=key_contains)

    def _match_all(
        self, *, type: MemoryType | None, key_contains: str | None
    ) -> list[Memory]:
        """Every ACTIVE memory matching the filter, with no limit."""
        clauses = ["status != 'DELETED'"]
        params: list[Any] = []
        if type:
            clauses.append("type = ?")
            params.append(str(type))
        if key_contains:
            needle = f"%{key_contains.strip().casefold()}%"
            clauses.append("(LOWER(key) LIKE ? OR LOWER(value_json) LIKE ?)")
            params.extend([needle, needle])
        with self._connect() as conn:
            rows = conn.execute(
                f"SELECT * FROM memories WHERE {' AND '.join(clauses)} "
                f"ORDER BY updated_at DESC",
                params,
            ).fetchall()
        return [_row_to_memory(row) for row in rows]

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
