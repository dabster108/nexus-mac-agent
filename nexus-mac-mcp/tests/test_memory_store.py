"""The SQLite-backed memory store: CRUD, search, staleness, soft delete."""

from __future__ import annotations

from pathlib import Path

import pytest

from nexus_mac_mcp.core.memory_store import (
    MAX_LIST_LIMIT,
    MAX_VALUE_BYTES,
    MemoryError,
    MemoryStore,
)
from nexus_mac_mcp.core.memory_types import (
    ConfidenceLevel,
    MemorySource,
    MemoryStatus,
    MemoryType,
)


# --- create / read -----------------------------------------------------


def test_create_and_get_by_id(memory_store: MemoryStore) -> None:
    memory = memory_store.create(
        type=MemoryType.PROJECT,
        key="nexus_project",
        value={"name": "NEXUS", "path": "~/Documents/nexus"},
        source=MemorySource.USER,
    )

    fetched = memory_store.get(memory_id=memory.id)

    assert fetched is not None
    assert fetched.key == "nexus_project"
    assert fetched.value == {"name": "NEXUS", "path": "~/Documents/nexus"}
    assert fetched.status is MemoryStatus.ACTIVE
    assert fetched.confidence == 1.0  # USER source default


def test_get_by_key(memory_store: MemoryStore) -> None:
    memory_store.create(
        type=MemoryType.WORKSPACE, key="backend", value={"framework": "FastAPI"},
        source=MemorySource.USER,
    )

    fetched = memory_store.get(key="backend")

    assert fetched is not None
    assert fetched.value == {"framework": "FastAPI"}


def test_get_by_key_narrowed_by_type(memory_store: MemoryStore) -> None:
    memory_store.create(type=MemoryType.FACT, key="x", value={"a": 1}, source=MemorySource.USER)

    assert memory_store.get(key="x", type=MemoryType.FACT) is not None
    assert memory_store.get(key="x", type=MemoryType.PROJECT) is None


def test_get_requires_an_id_or_key(memory_store: MemoryStore) -> None:
    with pytest.raises(MemoryError, match="memory_id or key"):
        memory_store.get()


def test_get_missing_returns_none(memory_store: MemoryStore) -> None:
    assert memory_store.get(memory_id="mem_nope") is None


def test_a_memory_needs_a_key(memory_store: MemoryStore) -> None:
    with pytest.raises(MemoryError, match="needs a key"):
        memory_store.create(type=MemoryType.FACT, key="  ", value={"a": 1}, source=MemorySource.USER)


def test_a_memorys_value_must_be_an_object(memory_store: MemoryStore) -> None:
    with pytest.raises(MemoryError, match="must be an object"):
        memory_store.create(
            type=MemoryType.FACT, key="x", value="not a dict", source=MemorySource.USER  # type: ignore[arg-type]
        )


# --- confidence by source ------------------------------------------------


@pytest.mark.parametrize(
    ("source", "expected"),
    [(MemorySource.USER, 1.0), (MemorySource.SYSTEM, 0.85), (MemorySource.MISSION, 0.6)],
)
def test_default_confidence_by_source(
    memory_store: MemoryStore, source: MemorySource, expected: float
) -> None:
    memory = memory_store.create(type=MemoryType.FACT, key="x", value={"a": 1}, source=source)

    assert memory.confidence == expected


def test_confidence_can_be_overridden(memory_store: MemoryStore) -> None:
    memory = memory_store.create(
        type=MemoryType.FACT, key="x", value={"a": 1}, source=MemorySource.USER, confidence=0.4
    )

    assert memory.confidence == 0.4


# --- duplicates (update, not a new row) -----------------------------------


def test_saving_the_same_type_and_key_updates_in_place(memory_store: MemoryStore) -> None:
    first = memory_store.create(
        type=MemoryType.PROJECT, key="nexus", value={"path": "/a"}, source=MemorySource.USER
    )
    second = memory_store.create(
        type=MemoryType.PROJECT, key="nexus", value={"path": "/b"}, source=MemorySource.USER
    )

    assert second.id == first.id
    assert memory_store.get(memory_id=first.id).value == {"path": "/b"}
    assert len(memory_store.list(type=MemoryType.PROJECT)) == 1


def test_the_same_key_under_a_different_type_is_a_separate_memory(
    memory_store: MemoryStore,
) -> None:
    a = memory_store.create(type=MemoryType.PROJECT, key="x", value={"n": 1}, source=MemorySource.USER)
    b = memory_store.create(type=MemoryType.FACT, key="x", value={"n": 2}, source=MemorySource.USER)

    assert a.id != b.id
    assert len(memory_store.list()) == 2


# --- search / list ---------------------------------------------------------


def test_list_orders_newest_first(memory_store: MemoryStore) -> None:
    memory_store.create(type=MemoryType.FACT, key="a", value={}, source=MemorySource.USER)
    memory_store.create(type=MemoryType.FACT, key="b", value={}, source=MemorySource.USER)

    assert [m.key for m in memory_store.list()] == ["b", "a"]


def test_list_filters_by_type(memory_store: MemoryStore) -> None:
    memory_store.create(type=MemoryType.PROJECT, key="a", value={}, source=MemorySource.USER)
    memory_store.create(type=MemoryType.FACT, key="b", value={}, source=MemorySource.USER)

    assert [m.key for m in memory_store.list(type=MemoryType.PROJECT)] == ["a"]


def test_search_matches_the_key(memory_store: MemoryStore) -> None:
    memory_store.create(type=MemoryType.PROJECT, key="nexus_project", value={}, source=MemorySource.USER)
    memory_store.create(type=MemoryType.PROJECT, key="other_project", value={}, source=MemorySource.USER)

    assert [m.key for m in memory_store.list(query="nexus")] == ["nexus_project"]


def test_search_matches_the_value(memory_store: MemoryStore) -> None:
    memory_store.create(
        type=MemoryType.WORKSPACE, key="backend", value={"framework": "FastAPI"},
        source=MemorySource.USER,
    )
    memory_store.create(
        type=MemoryType.WORKSPACE, key="frontend", value={"framework": "Next.js"},
        source=MemorySource.USER,
    )

    assert [m.key for m in memory_store.list(query="fastapi")] == ["backend"]


def test_search_is_case_insensitive(memory_store: MemoryStore) -> None:
    memory_store.create(type=MemoryType.PROJECT, key="NEXUS", value={}, source=MemorySource.USER)

    assert len(memory_store.list(query="nexus")) == 1


def test_list_respects_the_limit(memory_store: MemoryStore) -> None:
    for i in range(5):
        memory_store.create(type=MemoryType.FACT, key=f"k{i}", value={}, source=MemorySource.USER)

    assert len(memory_store.list(limit=2)) == 2


def test_list_limit_is_capped(memory_store: MemoryStore) -> None:
    for i in range(3):
        memory_store.create(type=MemoryType.FACT, key=f"k{i}", value={}, source=MemorySource.USER)

    from nexus_mac_mcp.core.memory_store import MAX_LIST_LIMIT

    assert len(memory_store.list(limit=10_000)) <= MAX_LIST_LIMIT


# --- staleness (computed, never stored) ------------------------------------


def test_a_memory_with_a_real_path_is_not_stale(memory_store: MemoryStore, tmp_path: Path) -> None:
    memory = memory_store.create(
        type=MemoryType.WORKSPACE, key="backend", value={"path": str(tmp_path)},
        source=MemorySource.USER,
    )

    assert memory_store.is_stale(memory) is False


def test_a_memory_with_a_missing_path_is_stale(memory_store: MemoryStore, tmp_path: Path) -> None:
    memory = memory_store.create(
        type=MemoryType.WORKSPACE, key="backend", value={"path": str(tmp_path / "gone")},
        source=MemorySource.USER,
    )

    assert memory_store.is_stale(memory) is True


def test_a_memory_without_a_path_is_never_stale(memory_store: MemoryStore) -> None:
    memory = memory_store.create(
        type=MemoryType.USER_PREFERENCE, key="editor", value={"name": "vim"},
        source=MemorySource.USER,
    )

    assert memory_store.is_stale(memory) is False


def test_staleness_is_not_a_stored_column(memory_store: MemoryStore, tmp_path: Path) -> None:
    """Re-creating the directory un-stales the memory without any write."""
    missing = tmp_path / "reappears"
    memory = memory_store.create(
        type=MemoryType.WORKSPACE, key="w", value={"path": str(missing)}, source=MemorySource.USER
    )
    assert memory_store.is_stale(memory) is True

    missing.mkdir()

    assert memory_store.is_stale(memory_store.get(memory_id=memory.id)) is False


# --- delete (soft) -----------------------------------------------------


def test_delete_by_id(memory_store: MemoryStore) -> None:
    memory = memory_store.create(type=MemoryType.FACT, key="x", value={}, source=MemorySource.USER)

    deleted = memory_store.delete(memory_id=memory.id)

    assert [m.key for m in deleted] == ["x"]
    assert memory_store.get(memory_id=memory.id) is None
    assert memory_store.list() == []


def test_delete_by_key(memory_store: MemoryStore) -> None:
    memory_store.create(type=MemoryType.FACT, key="x", value={}, source=MemorySource.USER)

    deleted = memory_store.delete(key="x")

    assert len(deleted) == 1


def test_delete_by_type_is_bulk(memory_store: MemoryStore) -> None:
    memory_store.create(type=MemoryType.FACT, key="a", value={}, source=MemorySource.USER)
    memory_store.create(type=MemoryType.FACT, key="b", value={}, source=MemorySource.USER)
    memory_store.create(type=MemoryType.PROJECT, key="c", value={}, source=MemorySource.USER)

    deleted = memory_store.delete(type=MemoryType.FACT)

    assert {m.key for m in deleted} == {"a", "b"}
    assert [m.key for m in memory_store.list()] == ["c"]


def test_delete_by_key_contains(memory_store: MemoryStore) -> None:
    memory_store.create(type=MemoryType.PROJECT, key="nexus_backend", value={}, source=MemorySource.USER)
    memory_store.create(type=MemoryType.PROJECT, key="nexus_frontend", value={}, source=MemorySource.USER)
    memory_store.create(type=MemoryType.PROJECT, key="other", value={}, source=MemorySource.USER)

    deleted = memory_store.delete(key_contains="nexus")

    assert {m.key for m in deleted} == {"nexus_backend", "nexus_frontend"}


def test_wipe_all_deletes_everything(memory_store: MemoryStore) -> None:
    memory_store.create(type=MemoryType.FACT, key="a", value={}, source=MemorySource.USER)
    memory_store.create(type=MemoryType.PROJECT, key="b", value={}, source=MemorySource.USER)

    deleted = memory_store.delete(wipe_all=True)

    assert {m.key for m in deleted} == {"a", "b"}
    assert memory_store.list() == []


def test_an_oversized_memory_value_is_refused(memory_store: MemoryStore) -> None:
    """Phase 9: values were unbounded. The value is read back into the agent's
    transcript verbatim, so one oversized save poisons every later request."""
    with pytest.raises(MemoryError, match="too large"):
        memory_store.create(
            type=MemoryType.FACT,
            key="huge",
            value={"blob": "A" * (MAX_VALUE_BYTES + 1)},
            source=MemorySource.USER,
        )

    assert memory_store.get(key="huge") is None


def test_an_ordinary_memory_is_comfortably_under_the_limit(
    memory_store: MemoryStore,
) -> None:
    memory = memory_store.create(
        type=MemoryType.PROJECT,
        key="nexus",
        value={"path": "/Users/someone/Documents/distributed-systems-lab", "port": 8000},
        source=MemorySource.USER,
    )

    assert memory.value["port"] == 8000


def test_a_value_that_cannot_be_serialised_is_refused(memory_store: MemoryStore) -> None:
    with pytest.raises(MemoryError):
        memory_store.create(
            type=MemoryType.FACT, key="bad", value={"o": object()}, source=MemorySource.USER
        )


def test_wipe_all_deletes_past_the_list_limit(memory_store: MemoryStore) -> None:
    """Phase 9: deletion used to reuse list(), whose MAX_LIST_LIMIT exists to
    keep a *prompt* small. "Forget everything" reported deleting 50 and left
    the rest ACTIVE — the user believes data is gone when it is not."""
    for index in range(MAX_LIST_LIMIT + 10):
        memory_store.create(
            type=MemoryType.FACT, key=f"fact_{index:03d}", value={}, source=MemorySource.USER
        )

    deleted = memory_store.delete(wipe_all=True)

    assert len(deleted) == MAX_LIST_LIMIT + 10
    assert memory_store.list(limit=MAX_LIST_LIMIT) == []


def test_bulk_delete_by_type_is_not_truncated_either(memory_store: MemoryStore) -> None:
    for index in range(MAX_LIST_LIMIT + 5):
        memory_store.create(
            type=MemoryType.WORKSPACE, key=f"ws_{index:03d}", value={}, source=MemorySource.USER
        )
    memory_store.create(
        type=MemoryType.FACT, key="keep_me", value={}, source=MemorySource.USER
    )

    deleted = memory_store.delete(type=MemoryType.WORKSPACE)

    assert len(deleted) == MAX_LIST_LIMIT + 5
    # The filter is still respected: an unrelated memory survives.
    assert [m.key for m in memory_store.list()] == ["keep_me"]


def test_reads_stay_bounded_for_prompt_size(memory_store: MemoryStore) -> None:
    """The deletion fix must not have removed the cap on ordinary reads."""
    for index in range(MAX_LIST_LIMIT + 10):
        memory_store.create(
            type=MemoryType.FACT, key=f"fact_{index:03d}", value={}, source=MemorySource.USER
        )

    assert len(memory_store.list(limit=999)) == MAX_LIST_LIMIT


def test_delete_requires_a_filter(memory_store: MemoryStore) -> None:
    with pytest.raises(MemoryError, match="At least one filter"):
        memory_store.delete()


def test_deleting_nothing_matching_is_a_no_op(memory_store: MemoryStore) -> None:
    assert memory_store.delete(memory_id="mem_nope") == []


def test_delete_is_soft_the_row_survives_for_audit(memory_store: MemoryStore) -> None:
    memory = memory_store.create(type=MemoryType.FACT, key="x", value={"a": 1}, source=MemorySource.USER)

    memory_store.delete(memory_id=memory.id)

    with memory_store._connect() as conn:  # white-box: confirm it's not gone, just hidden
        row = conn.execute("SELECT status FROM memories WHERE id = ?", (memory.id,)).fetchone()
    assert row["status"] == "DELETED"


def test_a_deleted_key_can_be_reused(memory_store: MemoryStore) -> None:
    """Deleting frees the (type, key) slot for a fresh memory."""
    first = memory_store.create(type=MemoryType.FACT, key="x", value={"v": 1}, source=MemorySource.USER)
    memory_store.delete(memory_id=first.id)

    second = memory_store.create(type=MemoryType.FACT, key="x", value={"v": 2}, source=MemorySource.USER)

    assert second.id != first.id
    assert memory_store.get(key="x").value == {"v": 2}


# --- secrets never reach the database --------------------------------------


@pytest.mark.parametrize(
    ("key", "value"),
    [
        ("api_key", {"value": "gsk_abcdefghijklmnopqrstuvwxyz123456"}),
        ("groq_key", {"api_key": "gsk_abcdefghijklmnopqrstuvwxyz123456"}),
        ("note", {"text": "my password is hunter2hunter2"}),
        ("config", {"GITHUB_TOKEN": "ghp_abcdefghijklmnopqrstuvwxyz1234"}),
        ("env", {"dump": "GROQ_API_KEY=gsk_abcdefghijklmnopqrstuvwxyz123456"}),
        ("ssh", {"text": "-----BEGIN OPENSSH PRIVATE KEY-----\nabc\n-----END OPENSSH PRIVATE KEY-----"}),
    ],
)
def test_secret_shaped_content_is_refused(
    memory_store: MemoryStore, key: str, value: dict
) -> None:
    with pytest.raises(Exception, match="credential"):
        memory_store.create(type=MemoryType.FACT, key=key, value=value, source=MemorySource.USER)

    assert memory_store.list() == []


def test_a_refused_secret_never_touches_the_database_file(
    memory_store: MemoryStore,
) -> None:
    with pytest.raises(Exception):
        memory_store.create(
            type=MemoryType.FACT, key="k", value={"password": "hunter2hunter2"}, source=MemorySource.USER
        )

    with memory_store._connect() as conn:
        count = conn.execute("SELECT COUNT(*) AS n FROM memories").fetchone()["n"]
    assert count == 0


# --- the database lives outside any project workspace -----------------------


def test_default_db_path_is_under_home_dot_nexus() -> None:
    from nexus_mac_mcp.core.memory_store import DEFAULT_DB_DIR, DEFAULT_DB_NAME, default_db_path

    assert DEFAULT_DB_DIR == Path.home() / ".nexus"
    assert default_db_path() == Path.home() / ".nexus" / DEFAULT_DB_NAME


def test_db_path_is_overridable_for_tests(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    from nexus_mac_mcp.core.memory_store import default_db_path

    monkeypatch.setenv("NEXUS_MAC_DB_PATH", str(tmp_path / "custom.db"))

    assert default_db_path() == tmp_path / "custom.db"


# --- confidence, verification and contradiction (Phase 10) -----------------


def test_a_fresh_user_memory_reads_as_high_confidence(memory_store: MemoryStore) -> None:
    memory = memory_store.create(
        type=MemoryType.PROJECT, key="nexus", value={"path": "/x"},
        source=MemorySource.USER,
    )

    assert memory.confidence_level is ConfidenceLevel.HIGH
    # Writing a value is itself a verification: it was true just now.
    assert memory.last_verified_at is not None


def test_an_inferred_memory_reads_as_low_confidence(memory_store: MemoryStore) -> None:
    memory = memory_store.create(
        type=MemoryType.FACT, key="guess", value={"a": 1}, source=MemorySource.MISSION
    )

    assert memory.confidence_level is ConfidenceLevel.LOW


def test_an_old_unverified_memory_decays_to_medium() -> None:
    """§3: old-but-unverified is exactly where live evidence should win."""
    from nexus_mac_mcp.core.memory_types import confidence_level

    assert confidence_level(1.0, age_days=0) is ConfidenceLevel.HIGH
    assert confidence_level(1.0, age_days=365) is ConfidenceLevel.MEDIUM


def test_verifying_resets_the_decay_clock(memory_store: MemoryStore) -> None:
    memory = memory_store.create(
        type=MemoryType.PROJECT, key="nexus", value={"path": "/x"},
        source=MemorySource.USER,
    )

    verified = memory_store.verify(memory.id)

    assert verified.last_verified_at is not None
    assert verified.confidence_level is ConfidenceLevel.HIGH
    # Being right once does not make a memory *more* true.
    assert verified.confidence == memory.confidence


def test_a_contradicted_memory_is_marked_stale_but_kept(memory_store: MemoryStore) -> None:
    memory = memory_store.create(
        type=MemoryType.WORKSPACE, key="backend", value={"port": 8000},
        source=MemorySource.USER,
    )

    stale = memory_store.mark_stale(memory.id)

    assert stale.status is MemoryStatus.STALE
    assert stale.to_public_dict()["stale"] is True
    # Retained, not deleted: the user decides whether to forget it.
    assert memory_store.get(memory_id=memory.id) is not None


def test_saving_over_a_stale_memory_revives_it(memory_store: MemoryStore) -> None:
    memory = memory_store.create(
        type=MemoryType.WORKSPACE, key="backend", value={"port": 8000},
        source=MemorySource.USER,
    )
    memory_store.mark_stale(memory.id)

    updated = memory_store.create(
        type=MemoryType.WORKSPACE, key="backend", value={"port": 8123},
        source=MemorySource.USER,
    )

    assert updated.id == memory.id
    assert updated.status is MemoryStatus.ACTIVE
    assert updated.value == {"port": 8123}


def test_a_stale_memory_can_still_be_forgotten(memory_store: MemoryStore) -> None:
    memory = memory_store.create(
        type=MemoryType.FACT, key="wrong", value={}, source=MemorySource.USER
    )
    memory_store.mark_stale(memory.id)

    assert len(memory_store.delete(wipe_all=True)) == 1


def test_the_new_memory_types_round_trip(memory_store: MemoryStore) -> None:
    for memory_type in (MemoryType.DECISION, MemoryType.TASK_CONTEXT):
        memory = memory_store.create(
            type=memory_type, key=f"k_{memory_type}", value={"a": 1},
            source=MemorySource.USER,
        )
        assert memory_store.get(memory_id=memory.id).type is memory_type


def test_an_older_database_gains_the_new_column_without_losing_rows(
    tmp_path: Path,
) -> None:
    """A real `~/.nexus/nexus.db` predates last_verified_at."""
    import sqlite3

    path = tmp_path / "legacy.db"
    conn = sqlite3.connect(path)
    conn.executescript(
        """
        CREATE TABLE memories (
            id TEXT PRIMARY KEY, type TEXT NOT NULL, key TEXT NOT NULL,
            value_json TEXT NOT NULL, source TEXT NOT NULL, confidence REAL NOT NULL,
            status TEXT NOT NULL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL);
        """
    )
    conn.execute(
        "INSERT INTO memories VALUES ('mem_old','PROJECT','legacy','{}','USER',1.0,"
        "'ACTIVE','2026-01-01T00:00:00+00:00','2026-01-01T00:00:00+00:00')"
    )
    conn.commit()
    conn.close()

    store = MemoryStore(path)

    survivor = store.get(key="legacy")
    assert survivor is not None
    assert survivor.last_verified_at is None
    # Old and never verified, so it must not claim HIGH confidence.
    assert survivor.confidence_level is not ConfidenceLevel.HIGH
