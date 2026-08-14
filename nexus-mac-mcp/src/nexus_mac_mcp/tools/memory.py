"""Memory tools: list_memories, get_memory (SAFE), save_memory, delete_memory (CONFIRM).

Thin wrappers over :class:`~nexus_mac_mcp.core.memory_store.MemoryStore`. The
agent never touches SQLite directly — every read and write goes through here,
and every write goes through the store's secret check first.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Any

from nexus_mac_mcp.core.memory_secrets import SecretDetectedError
from nexus_mac_mcp.core.memory_store import MemoryError, MemoryStore
from nexus_mac_mcp.core.memory_types import MemorySource, MemoryType

VALID_TYPES = tuple(t.value for t in MemoryType)
VALID_SOURCES = tuple(s.value for s in MemorySource)


@lru_cache(maxsize=1)
def get_memory_store() -> MemoryStore:
    return MemoryStore()


def _failure(error: str) -> dict[str, Any]:
    return {"success": False, "error": error}


def _parse_type(type: str | None) -> MemoryType | None:
    if not type:
        return None
    try:
        return MemoryType(type.strip().upper())
    except ValueError as exc:
        raise MemoryError(
            f"'{type}' is not a memory type. Use one of: {', '.join(VALID_TYPES)}."
        ) from exc


def list_memories(
    query: str | None = None,
    type: str | None = None,
    limit: int = 20,
    store: MemoryStore | None = None,
) -> dict[str, Any]:
    """List/search memories. Staleness is reported, never hidden."""
    store = store or get_memory_store()
    try:
        parsed_type = _parse_type(type)
        memories = store.list(type=parsed_type, query=query, limit=limit)
    except MemoryError as exc:
        return _failure(str(exc))

    return {
        "success": True,
        "count": len(memories),
        "memories": [
            memory.to_public_dict(stale=store.is_stale(memory)) for memory in memories
        ],
    }


def get_memory(
    memory_id: str | None = None,
    key: str | None = None,
    type: str | None = None,
    store: MemoryStore | None = None,
) -> dict[str, Any]:
    """Fetch one memory by id, or by (type, key)."""
    store = store or get_memory_store()
    try:
        parsed_type = _parse_type(type)
        memory = store.get(memory_id=memory_id, key=key, type=parsed_type)
    except MemoryError as exc:
        return _failure(str(exc))

    if memory is None:
        return _failure("No matching memory was found.")
    return {"success": True, "memory": memory.to_public_dict(stale=store.is_stale(memory))}


def save_memory(
    type: str,
    key: str,
    value: dict[str, Any],
    source: str = "USER",
    store: MemoryStore | None = None,
) -> dict[str, Any]:
    """Remember one fact. Refuses anything that looks like a credential."""
    store = store or get_memory_store()
    try:
        parsed_type = _parse_type(type)
        if parsed_type is None:
            return _failure(f"A memory type is required. Use one of: {', '.join(VALID_TYPES)}.")
        try:
            parsed_source = MemorySource(source.strip().upper())
        except ValueError:
            return _failure(f"'{source}' is not a memory source. Use one of: {', '.join(VALID_SOURCES)}.")
        memory = store.create(type=parsed_type, key=key, value=value, source=parsed_source)
    except SecretDetectedError as exc:
        return _failure(str(exc))
    except MemoryError as exc:
        return _failure(str(exc))

    return {"success": True, "memory": memory.to_public_dict()}


def delete_memory(
    memory_id: str | None = None,
    key: str | None = None,
    type: str | None = None,
    key_contains: str | None = None,
    wipe_all: bool = False,
    store: MemoryStore | None = None,
) -> dict[str, Any]:
    """Forget one memory, or a bounded, explicit group of them.

    Exactly one filter must be given: ``memory_id``, ``key`` (with an optional
    ``type``), ``type``/``key_contains`` for a scoped bulk delete, or
    ``wipe_all=True`` for everything. There is no "no filter" default that
    deletes anything.
    """
    store = store or get_memory_store()
    try:
        parsed_type = _parse_type(type)
        deleted = store.delete(
            memory_id=memory_id, key=key, type=parsed_type,
            key_contains=key_contains, wipe_all=wipe_all,
        )
    except MemoryError as exc:
        return _failure(str(exc))

    return {
        "success": True,
        "count": len(deleted),
        "deleted_keys": [memory.key for memory in deleted],
    }
