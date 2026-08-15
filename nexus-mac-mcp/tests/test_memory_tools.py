"""The memory MCP tools: the thin layer between the store and the protocol."""

from __future__ import annotations

import stat
from pathlib import Path

import pytest

from nexus_mac_mcp.core.memory_store import MemoryError, MemoryStore
from nexus_mac_mcp.core.memory_types import MemorySource, MemoryType
from nexus_mac_mcp.tools import memory


def test_save_and_list(memory_store: MemoryStore) -> None:
    result = memory.save_memory(
        "PROJECT", "nexus_project", {"name": "NEXUS", "path": "~/Documents/nexus"},
        store=memory_store,
    )

    assert result["success"] is True
    assert result["memory"]["key"] == "nexus_project"

    listed = memory.list_memories(store=memory_store)
    assert listed["count"] == 1
    assert listed["memories"][0]["key"] == "nexus_project"


def test_save_defaults_to_user_source(memory_store: MemoryStore) -> None:
    result = memory.save_memory("FACT", "x", {"a": 1}, store=memory_store)

    assert result["memory"]["source"] == "USER"
    assert result["memory"]["confidence"] == 1.0


def test_save_rejects_an_unknown_type(memory_store: MemoryStore) -> None:
    result = memory.save_memory("NOT_A_TYPE", "x", {"a": 1}, store=memory_store)

    assert result["success"] is False
    assert "memory type" in result["error"]


def test_save_rejects_an_unknown_source(memory_store: MemoryStore) -> None:
    result = memory.save_memory("FACT", "x", {"a": 1}, source="ROBOT", store=memory_store)

    assert result["success"] is False
    assert "memory source" in result["error"]


def test_save_refuses_a_secret(memory_store: MemoryStore) -> None:
    result = memory.save_memory(
        "FACT", "k", {"api_key": "gsk_abcdefghijklmnopqrstuvwxyz123456"}, store=memory_store
    )

    assert result["success"] is False
    assert "credential" in result["error"]
    assert memory.list_memories(store=memory_store)["count"] == 0


def test_get_by_id(memory_store: MemoryStore) -> None:
    saved = memory.save_memory("FACT", "x", {"a": 1}, store=memory_store)

    result = memory.get_memory(memory_id=saved["memory"]["id"], store=memory_store)

    assert result["success"] is True
    assert result["memory"]["value"] == {"a": 1}


def test_get_missing_is_a_clean_failure(memory_store: MemoryStore) -> None:
    result = memory.get_memory(memory_id="mem_nope", store=memory_store)

    assert result["success"] is False
    assert "No matching memory" in result["error"]


def test_list_reports_staleness(memory_store: MemoryStore, tmp_path) -> None:
    memory.save_memory(
        "WORKSPACE", "backend", {"path": str(tmp_path / "gone")}, store=memory_store
    )

    result = memory.list_memories(store=memory_store)

    assert result["memories"][0]["stale"] is True


def test_list_does_not_report_staleness_when_fresh(memory_store: MemoryStore, tmp_path) -> None:
    memory.save_memory("WORKSPACE", "backend", {"path": str(tmp_path)}, store=memory_store)

    result = memory.list_memories(store=memory_store)

    assert "stale" not in result["memories"][0]


def test_search_by_query(memory_store: MemoryStore) -> None:
    memory.save_memory("PROJECT", "nexus", {"name": "NEXUS"}, store=memory_store)
    memory.save_memory("PROJECT", "other", {"name": "Other"}, store=memory_store)

    result = memory.list_memories(query="nexus", store=memory_store)

    assert result["count"] == 1
    assert result["memories"][0]["key"] == "nexus"


def test_delete_by_id(memory_store: MemoryStore) -> None:
    saved = memory.save_memory("FACT", "x", {"a": 1}, store=memory_store)

    result = memory.delete_memory(memory_id=saved["memory"]["id"], store=memory_store)

    assert result["success"] is True
    assert result["count"] == 1
    assert memory.get_memory(memory_id=saved["memory"]["id"], store=memory_store)["success"] is False


def test_delete_with_no_filter_is_refused(memory_store: MemoryStore) -> None:
    result = memory.delete_memory(store=memory_store)

    assert result["success"] is False
    assert "filter" in result["error"]


def test_wipe_all(memory_store: MemoryStore) -> None:
    memory.save_memory("FACT", "a", {}, store=memory_store)
    memory.save_memory("PROJECT", "b", {}, store=memory_store)

    result = memory.delete_memory(wipe_all=True, store=memory_store)

    assert result["count"] == 2
    assert memory.list_memories(store=memory_store)["count"] == 0


def test_delete_by_key_contains_forget_everything_about_a_project(
    memory_store: MemoryStore,
) -> None:
    memory.save_memory("PROJECT", "nexus_backend", {}, store=memory_store)
    memory.save_memory("WORKSPACE", "nexus_frontend", {}, store=memory_store)
    memory.save_memory("PROJECT", "unrelated", {}, store=memory_store)

    result = memory.delete_memory(key_contains="nexus", store=memory_store)

    assert result["count"] == 2
    assert set(result["deleted_keys"]) == {"nexus_backend", "nexus_frontend"}
    assert memory.list_memories(store=memory_store)["count"] == 1


# --- an unusable database (Phase 9) ---------------------------------------


@pytest.fixture
def corrupt_db(tmp_path: Path) -> Path:
    path = tmp_path / "corrupt.db"
    path.write_bytes(b"this is not a sqlite database" * 100)
    return path


def test_a_corrupt_database_is_reported_as_an_ordinary_tool_failure(
    corrupt_db: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Phase 9: sqlite3 errors escaped as protocol-level errors, losing the
    `success: false` shape every other refusal uses."""
    monkeypatch.setenv("NEXUS_MAC_DB_PATH", str(corrupt_db))
    memory.get_memory_store.cache_clear()

    for result in (
        memory.list_memories(),
        memory.get_memory(key="x"),
        memory.save_memory(type="FACT", key="x", value={"a": 1}),
        memory.delete_memory(wipe_all=True),
    ):
        assert result["success"] is False
        assert "memory database is unavailable" in result["error"]

    memory.get_memory_store.cache_clear()


def test_an_unusable_database_never_names_the_path_or_the_sqlite_error(
    corrupt_db: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("NEXUS_MAC_DB_PATH", str(corrupt_db))
    memory.get_memory_store.cache_clear()

    error = memory.list_memories()["error"]

    assert str(corrupt_db) not in error
    assert "sqlite" not in error.casefold()
    assert "not a database" not in error.casefold()

    memory.get_memory_store.cache_clear()


def test_a_read_only_database_refuses_writes_but_still_reads(tmp_path: Path) -> None:
    path = tmp_path / "ro.db"
    store = MemoryStore(path)
    store.create(
        type=MemoryType.FACT, key="before", value={"a": 1}, source=MemorySource.USER
    )
    path.chmod(stat.S_IRUSR)
    try:
        with pytest.raises(MemoryError, match="unavailable"):
            store.create(
                type=MemoryType.FACT, key="after", value={"a": 2}, source=MemorySource.USER
            )
        # Reading is unaffected, so the agent keeps working with what it has.
        assert store.get(key="before") is not None
    finally:
        path.chmod(stat.S_IRUSR | stat.S_IWUSR)
