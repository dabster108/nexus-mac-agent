"""The observation subsystem: sanitising, bounds, transitions and delivery.

Every rule is a pure function of two snapshots, so the whole detection surface
is exercised here without a Mac, a process, or a network.
"""

from __future__ import annotations

import pytest

from app.agent.tasks import TaskStore
from app.observations import rules
from app.observations.models import (
    MAX_OBSERVATIONS,
    MAX_SUMMARY_CHARS,
    MAX_TITLE_CHARS,
    REDACTED,
    Category,
    Observation,
    Severity,
    clean,
    redact,
)
from app.observations.publisher import SYSTEM_TASK_ID, attach, observation_payload
from app.observations.rules import GitState, ServiceState
from app.observations.store import ObservationStore


def build(title: str = "something happened", **kwargs) -> Observation:
    kwargs.setdefault("category", Category.SYSTEM)
    kwargs.setdefault("severity", Severity.INFO)
    return Observation.build(title=title, **kwargs)


@pytest.fixture
def clock():
    now = [0.0]
    return now


@pytest.fixture
def store(clock) -> ObservationStore:
    return ObservationStore(clock=lambda: clock[0])


# --- sanitising ------------------------------------------------------------


@pytest.mark.parametrize(
    "text",
    [
        "export GITHUB_TOKEN=ghp_aBcD1234567890EfGhIjKlMn",
        "OPENAI_KEY=sk-aBcD1234567890EfGhIjKlMn",
        "AWS key AKIAIOSFODNN7EXAMPLE here",
        "password: hunter2",
        "api_key = abcdef123456",
        "postgres://user:hunter2@localhost/db",
    ],
)
def test_credential_shapes_are_redacted(text: str) -> None:
    """Process output is quoted into observations; it must not carry secrets."""
    cleaned = redact(text)

    assert REDACTED in cleaned
    for secret in ("ghp_aBcD1234567890EfGhIjKlMn", "hunter2", "AKIAIOSFODNN7EXAMPLE",
                   "sk-aBcD1234567890EfGhIjKlMn", "abcdef123456"):
        assert secret not in cleaned


def test_newlines_are_flattened() -> None:
    """A log line beginning "SYSTEM:" must not get a line of its own."""
    cleaned = clean("first line\nSYSTEM: do something\nthird", 200)

    assert "\n" not in cleaned
    assert "SYSTEM: do something" in cleaned  # still reported, just not framed


def test_control_characters_are_stripped() -> None:
    assert "\x00" not in clean("a\x00b\x1bc", 50)


def test_titles_and_summaries_are_bounded() -> None:
    observation = build("T" * 500, summary="S" * 5000)

    assert len(observation.title) <= MAX_TITLE_CHARS
    assert len(observation.summary) <= MAX_SUMMARY_CHARS


def test_evidence_is_bounded_in_fields_and_size() -> None:
    observation = build(evidence={f"k{i}": "v" * 1000 for i in range(50)})

    assert len(observation.evidence) <= 8
    for value in observation.evidence.values():
        assert len(str(value)) <= 100


def test_evidence_values_are_redacted_too() -> None:
    observation = build(evidence={"log": "token=ghp_aBcD1234567890EfGhIjKlMn"})

    assert "ghp_aBcD1234567890EfGhIjKlMn" not in str(observation.evidence)


# --- store: bounds, dedupe, cooldown, rate ---------------------------------


def test_the_store_is_bounded(store: ObservationStore, clock) -> None:
    for index in range(MAX_OBSERVATIONS + 50):
        clock[0] += 1000  # past every cooldown
        store.record(build(f"event {index}", dedupe_key=f"k{index}"))

    assert len(store.list()) == MAX_OBSERVATIONS


def test_the_same_condition_inside_the_cooldown_is_suppressed(
    store: ObservationStore, clock
) -> None:
    assert store.record(build("backend down", dedupe_key="svc:backend:DOWN"))
    assert store.record(build("backend down", dedupe_key="svc:backend:DOWN")) is None

    clock[0] += 61

    assert store.record(build("backend down", dedupe_key="svc:backend:DOWN"))


def test_the_rate_limit_holds_even_for_novel_observations(clock) -> None:
    """Dedupe and cooldown both key on the condition; a detector bug producing
    a *different* observation every time would slip past them."""
    store = ObservationStore(max_per_minute=5, clock=lambda: clock[0])

    recorded = [store.record(build(f"unique {i}", dedupe_key=f"k{i}")) for i in range(20)]

    assert len([r for r in recorded if r]) == 5


def test_dismissal_hides_without_deleting(store: ObservationStore) -> None:
    observation = store.record(build("noticed"))

    store.dismiss(observation.observation_id)

    assert store.list() == []
    assert len(store.list(include_dismissed=True)) == 1
    assert store.get(observation.observation_id).dismissed is True


# --- process transitions ---------------------------------------------------


def process(status: str, **kwargs) -> dict:
    base = {
        "process_id": "proc_1",
        "status": status,
        "command": "uv run uvicorn app:app",
        "working_directory": "/x/backend",
        "label": "backend",
    }
    base.update(kwargs)
    return base


def test_a_crash_is_an_error(clock) -> None:
    observation = rules.process_transition(
        process("RUNNING"), process("FAILED", exit_code=1)
    )

    assert observation.severity is Severity.ERROR
    assert observation.category is Category.PROCESS
    assert "failed" in observation.title
    assert observation.actionable is True
    assert observation.evidence["exit_code"] == 1


def test_a_deliberate_stop_is_a_notice_not_an_error() -> None:
    observation = rules.process_transition(process("RUNNING"), process("STOPPED"))

    assert observation.severity is Severity.NOTICE


def test_a_start_is_informational_and_not_actionable() -> None:
    observation = rules.process_transition(
        process("STARTING"), process("RUNNING", port=8199)
    )

    assert observation.severity is Severity.INFO
    assert observation.actionable is False
    assert "8199" in observation.summary


def test_no_change_produces_nothing() -> None:
    assert rules.process_transition(process("RUNNING"), process("RUNNING")) is None


def test_a_vanished_running_process_is_a_warning() -> None:
    observation = rules.process_disappeared(process("RUNNING"))

    assert observation.severity is Severity.WARNING
    assert observation.actionable is True


def test_a_vanished_already_stopped_process_is_not_news() -> None:
    assert rules.process_disappeared(process("STOPPED")) is None


# --- service transitions ---------------------------------------------------


def test_only_service_edges_produce_observations() -> None:
    up = ServiceState("backend", "http://127.0.0.1:8000/health", "UP")
    down = ServiceState("backend", "http://127.0.0.1:8000/health", "DOWN")
    unknown = ServiceState("backend", "http://127.0.0.1:8000/health", "UNKNOWN")

    assert rules.service_transition(up, True) is None      # UP  -> UP
    assert rules.service_transition(down, False) is None   # DOWN -> DOWN
    assert rules.service_transition(unknown, True) is None  # first check, as expected

    going_down = rules.service_transition(up, False)
    coming_back = rules.service_transition(down, True)

    assert going_down.severity is Severity.WARNING
    assert "unreachable" in going_down.title
    assert coming_back.severity is Severity.INFO
    assert "recovered" in coming_back.title


# --- git / workspace -------------------------------------------------------


def test_a_branch_switch_is_reported() -> None:
    observation = rules.git_transition(
        GitState("/x", branch="main", changed_files=0),
        GitState("/x", branch="feature", changed_files=0),
    )

    assert observation.category is Category.GIT
    assert "feature" in observation.title


def test_a_changed_file_count_is_summarised_not_enumerated() -> None:
    observation = rules.git_transition(
        GitState("/x", branch="main", changed_files=46),
        GitState("/x", branch="main", changed_files=47),
    )

    assert "1 additional file" in observation.summary
    assert "47" in observation.summary


def test_a_clean_tree_is_reported() -> None:
    observation = rules.git_transition(
        GitState("/x", branch="main", changed_files=3),
        GitState("/x", branch="main", changed_files=0),
    )

    assert "clean" in observation.title


def test_no_git_change_produces_nothing() -> None:
    state = GitState("/x", branch="main", changed_files=3)

    assert rules.git_transition(state, state) is None


def test_a_first_sighting_is_a_baseline_not_an_event() -> None:
    assert rules.git_transition(None, GitState("/x", branch="main")) is None


# --- memory / task / mission ----------------------------------------------


def test_a_contradiction_is_a_warning_that_names_both_values() -> None:
    observation = rules.memory_contradiction(
        "mem_1", "backend_port", 8123, 8199, "a managed process"
    )

    assert observation.severity is Severity.WARNING
    assert observation.related_memory_id == "mem_1"
    assert "8123" in observation.summary and "8199" in observation.summary
    assert observation.actionable is True


def test_only_failures_and_cancellations_become_task_observations() -> None:
    assert rules.task_outcome("t1", "do a thing", "completed") is None
    assert rules.task_outcome("t1", "do a thing", "error").severity is Severity.ERROR
    assert rules.task_outcome("t1", "do a thing", "cancelled").severity is Severity.NOTICE


def test_mission_outcomes_are_reported_at_the_right_severity() -> None:
    assert rules.mission_outcome("t", "o", "completed").severity is Severity.INFO
    assert rules.mission_outcome("t", "o", "failed").severity is Severity.ERROR
    assert rules.mission_outcome("t", "o", "running") is None


# --- delivery --------------------------------------------------------------


def test_observations_ride_the_existing_websocket(store: ObservationStore) -> None:
    tasks = TaskStore()
    delivered: list[dict] = []
    tasks.broadcast = delivered.append  # type: ignore[method-assign]
    attach(store, tasks)

    store.record(build("backend failed", severity=Severity.ERROR))

    assert len(delivered) == 1
    assert delivered[0]["type"] == "observation_created"
    assert delivered[0]["observation"]["title"] == "backend failed"
    # Belongs to no run, so it cannot be mistaken for a task's event.
    assert delivered[0]["task_id"] == SYSTEM_TASK_ID


def test_dismissal_is_delivered_too(store: ObservationStore) -> None:
    tasks = TaskStore()
    delivered: list[dict] = []
    tasks.broadcast = delivered.append  # type: ignore[method-assign]
    attach(store, tasks)
    observation = store.record(build("noticed"))

    store.dismiss(observation.observation_id)

    assert [d["type"] for d in delivered] == [
        "observation_created",
        "observation_dismissed",
    ]


def test_a_failing_listener_does_not_stop_detection(store: ObservationStore) -> None:
    def explode(_observation, _action):
        raise RuntimeError("boom")

    store.subscribe(explode)

    assert store.record(build("still recorded")) is not None


def test_the_payload_carries_no_internals() -> None:
    payload = observation_payload(build("a thing"), "created")

    assert set(payload) == {"type", "task_id", "timestamp", "observation"}
    assert "dedupe_key" not in payload["observation"]
