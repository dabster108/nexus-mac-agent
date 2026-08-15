"""The suggestion layer: what earns a suggestion, and what stops it nagging.

The rules are pure functions of an observation, so the whole decision surface
is exercised here without a Mac, a process, or a model.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from app.agent.tasks import TaskStore
from app.observations.models import Category as ObservationCategory
from app.observations.models import Observation, Severity
from app.observations.store import ObservationStore
from app.suggestions import rules
from app.suggestions.engine import SuggestionEngine
from app.suggestions.models import Category, Status, SuggestedAction, Suggestion
from app.suggestions.publisher import attach
from app.suggestions.store import SuggestionStore


def crash(process_id: str = "proc_1", exit_code: int = 1) -> Observation:
    return Observation.build(
        category=ObservationCategory.PROCESS,
        severity=Severity.ERROR,
        title="backend failed",
        summary="stopped unexpectedly",
        actionable=True,
        related_process_id=process_id,
        workspace="/x/backend",
        evidence={"exit_code": exit_code, "command": "uv run uvicorn"},
    )


def build(key: str = "k", **kwargs) -> Suggestion:
    kwargs.setdefault("category", Category.PROCESS)
    kwargs.setdefault("severity", Severity.INFO)
    kwargs.setdefault("title", "a suggestion")
    kwargs.setdefault("description", "d")
    kwargs.setdefault("reason", "r")
    kwargs.setdefault("action", SuggestedAction(intent="investigate_process", prompt="look"))
    return Suggestion.build(key=key, **kwargs)


@pytest.fixture
def clock():
    return [0.0]


@pytest.fixture
def store(clock) -> SuggestionStore:
    return SuggestionStore(clock=lambda: clock[0])


# --- what earns a suggestion ----------------------------------------------


def test_a_crash_earns_an_investigation() -> None:
    suggestion = rules.from_observation(crash())

    assert suggestion.category is Category.PROCESS
    assert suggestion.action.intent == "investigate_process"
    assert "proc_1" in suggestion.action.prompt
    # An investigation must not become a change.
    assert "Do not change anything" in suggestion.action.prompt


def test_good_news_earns_nothing() -> None:
    started = Observation.build(
        category=ObservationCategory.PROCESS,
        severity=Severity.INFO,
        title="backend started",
        actionable=False,
    )

    assert rules.from_observation(started) is None


def test_a_repeatedly_failing_process_is_described_as_such() -> None:
    once = rules.from_observation(crash(), repeats=1)
    thrice = rules.from_observation(crash(), repeats=3)

    assert "keeps stopping" in thrice.title
    assert "3 times" in thrice.description
    assert thrice.key != once.key  # a different condition, not a repeat


def test_a_service_recovery_earns_nothing() -> None:
    recovered = Observation.build(
        category=ObservationCategory.SERVICE,
        severity=Severity.INFO,
        title="frontend recovered",
        actionable=False,
    )

    assert rules.from_observation(recovered) is None


def test_an_ordinary_amount_of_uncommitted_work_earns_nothing() -> None:
    small = Observation.build(
        category=ObservationCategory.GIT,
        severity=Severity.INFO,
        title="Workspace changed",
        evidence={"changed_files": 3},
    )
    large = Observation.build(
        category=ObservationCategory.GIT,
        severity=Severity.INFO,
        title="Workspace changed",
        workspace="/x",
        evidence={"changed_files": 25},
    )

    assert rules.from_observation(small) is None
    assert "25 uncommitted changes" in rules.from_observation(large).title


def test_a_contradicted_memory_offers_an_update() -> None:
    observation = Observation.build(
        category=ObservationCategory.MEMORY,
        severity=Severity.WARNING,
        title="A remembered fact may be out of date",
        related_memory_id="mem_1",
        evidence={"stored": 8123, "observed": 8199, "memory_id": "mem_1"},
    )

    suggestion = rules.from_observation(observation)

    assert suggestion.action.intent == "update_memory"
    assert "8199" in suggestion.action.prompt


def test_a_long_running_process_is_noticed() -> None:
    suggestion = rules.long_running_process(
        {"process_id": "p1", "status": "RUNNING", "runtime_seconds": 7 * 3600,
         "label": "dev server"}
    )

    assert "7 hours" in suggestion.title
    assert rules.long_running_process(
        {"process_id": "p1", "status": "RUNNING", "runtime_seconds": 60}
    ) is None


# --- a suggestion is not an action ----------------------------------------


def test_a_suggested_action_carries_no_tool_or_arguments() -> None:
    """The field that could quietly become an execution path. It holds an
    intent label, identifiers and a sentence — nothing callable."""
    payload = rules.from_observation(crash()).action.to_public_dict()

    assert set(payload) <= {"intent", "prompt", "process_id", "memory_key", "workspace"}
    assert "tool" not in payload
    assert "arguments" not in payload
    assert "args" not in payload


def test_accepting_records_but_performs_nothing(store: SuggestionStore) -> None:
    offered = store.offer(build())

    accepted = store.accept(offered.suggestion_id)

    assert accepted.status is Status.ACCEPTED
    assert store.pending() == []


# --- deduplication, cooldown, expiry, bounds -------------------------------


def test_one_condition_produces_one_suggestion(store: SuggestionStore) -> None:
    """A crash must not appear as "crashed", "stopped" and "failed"."""
    assert store.offer(build(key="process:p1:stopped", title="backend crashed"))
    assert store.offer(build(key="process:p1:stopped", title="process failed")) is None
    assert store.offer(build(key="process:p1:stopped", title="backend unavailable")) is None

    assert len(store.pending()) == 1


def test_dismissing_keeps_the_same_condition_quiet(store: SuggestionStore, clock) -> None:
    first = store.offer(build(key="svc:down"))
    store.dismiss(first.suggestion_id)

    assert store.offer(build(key="svc:down")) is None

    clock[0] += 1801

    assert store.offer(build(key="svc:down")) is not None


def test_pending_suggestions_are_capped(clock) -> None:
    store = SuggestionStore(max_pending=3, clock=lambda: clock[0])

    offered = [store.offer(build(key=f"k{i}")) for i in range(10)]

    assert len([o for o in offered if o]) == 3


def test_the_rate_limit_holds(clock) -> None:
    store = SuggestionStore(max_per_minute=2, max_pending=100, clock=lambda: clock[0])

    offered = [store.offer(build(key=f"k{i}")) for i in range(10)]

    assert len([o for o in offered if o]) == 2


def test_storage_is_bounded(clock) -> None:
    store = SuggestionStore(max_suggestions=5, max_pending=100, max_per_minute=1000,
                            clock=lambda: clock[0])

    for index in range(50):
        store.offer(build(key=f"k{index}"))

    assert len(store.list(include_resolved=True)) == 5


def test_a_suggestion_expires(store: SuggestionStore) -> None:
    offered = store.offer(build(key="k", ttl_seconds=0.0))

    # Expiry is computed on read: nothing needed a timer.
    assert store.get(offered.suggestion_id).status is Status.EXPIRED
    assert store.pending() == []


def test_expiry_is_announced(store: SuggestionStore) -> None:
    delivered: list[tuple[str, str]] = []
    store.subscribe(lambda s, action: delivered.append((s.suggestion_id, action)))

    offered = store.offer(build(key="k", ttl_seconds=0.0))
    store.list()

    assert (offered.suggestion_id, "expired") in delivered


# --- engine ----------------------------------------------------------------


def test_the_engine_turns_observations_into_suggestions() -> None:
    observations = ObservationStore()
    suggestions = SuggestionStore()
    SuggestionEngine(suggestions).attach_to(observations)

    observations.record(crash())

    assert len(suggestions.pending()) == 1
    assert suggestions.pending()[0].action.intent == "investigate_process"


def test_the_engine_counts_repeats_across_observations() -> None:
    observations = ObservationStore(cooldown_seconds=0.0)
    suggestions = SuggestionStore()
    SuggestionEngine(suggestions).attach_to(observations)

    for _ in range(3):
        observations.record(crash())

    assert any("keeps stopping" in s.title for s in suggestions.pending())


def test_a_failing_engine_does_not_break_observing() -> None:
    observations = ObservationStore()
    engine = SuggestionEngine(SuggestionStore())
    engine.attach_to(observations)
    engine.consider = lambda _o: (_ for _ in ()).throw(RuntimeError("boom"))  # type: ignore[assignment]

    assert observations.record(crash()) is not None


# --- memory suggestions ----------------------------------------------------


def test_an_explicit_durable_statement_is_offered() -> None:
    engine = SuggestionEngine(SuggestionStore())

    suggestion = engine.consider_message("From now on my backend usually runs on port 8000.")

    assert suggestion is not None
    assert suggestion.action.intent == "save_memory"
    assert "Remember that" in suggestion.action.prompt
    assert "8000" in suggestion.action.prompt


def test_a_statement_of_current_state_is_not_offered() -> None:
    """§8's exact distinction: "runs on" is how it is set up, "is running on"
    is what happens to be true this minute."""
    engine = SuggestionEngine(SuggestionStore())

    assert engine.consider_message("The backend is running on port 8000.") is None


@pytest.mark.parametrize(
    "message",
    [
        "The backend is broken.",
        "We might use port 8000.",
        "What port does the backend use?",
        "Thanks!",
    ],
)
def test_nothing_is_offered_for_these(message: str) -> None:
    assert SuggestionEngine(SuggestionStore()).consider_message(message) is None


def test_a_memory_suggestion_saves_nothing_by_itself() -> None:
    """It produces a sentence. save_memory is CONFIRM, so the user sees the
    value before it exists — two confirmations for one fact, deliberately."""
    engine = SuggestionEngine(SuggestionStore())

    suggestion = engine.consider_message("I prefer pytest for this project.")

    assert suggestion.action.intent == "save_memory"
    assert "memory_id" not in suggestion.to_public_dict()
    assert suggestion.status is Status.PENDING


# --- delivery --------------------------------------------------------------


def test_suggestions_ride_the_existing_websocket(store: SuggestionStore) -> None:
    tasks = TaskStore()
    delivered: list[dict] = []
    tasks.broadcast = delivered.append  # type: ignore[method-assign]
    attach(store, tasks)

    offered = store.offer(build())
    store.dismiss(offered.suggestion_id)

    assert [d["type"] for d in delivered] == [
        "suggestion_created",
        "suggestion_dismissed",
    ]
    assert delivered[0]["suggestion"]["title"] == "a suggestion"
    assert delivered[0]["task_id"] == "system"


def test_the_payload_carries_no_internals(store: SuggestionStore) -> None:
    payload = build().to_public_dict()

    assert "key" not in payload  # the dedupe key is ours, not the client's
    assert set(payload["suggested_action"]) <= {
        "intent", "prompt", "process_id", "memory_key", "workspace"
    }
