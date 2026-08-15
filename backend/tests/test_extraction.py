"""Automatic memory extraction, and everything it must decline to remember.

§9's asymmetry drives the shape of this file: there are far more tests for
what is *not* extracted than for what is. A missed memory costs one sentence
next time; a wrong one is a false fact that steers later answers.
"""

from __future__ import annotations

import pytest

from app.context.extraction import suggest


@pytest.mark.parametrize(
    "message",
    [
        "We're using port 8123 for the backend now.",
        "We are using port 8123 for the backend now.",
        "I'm using port 8123 for the backend.",
    ],
)
def test_a_stated_decision_is_offered(message: str) -> None:
    suggestion = suggest(message)

    assert suggestion is not None
    assert suggestion.type == "DECISION"
    assert suggestion.value["port"] == 8123


def test_the_thing_the_port_belongs_to_is_captured() -> None:
    suggestion = suggest("The backend now runs on port 8123.")

    assert suggestion is not None
    assert suggestion.key == "backend_port"


def test_the_active_workspace_is_recorded_with_the_fact() -> None:
    suggestion = suggest(
        "The backend now runs on port 8123.", workspace="/x/nexus"
    )

    assert suggestion.value["path"] == "/x/nexus"


# --- what must never be extracted ------------------------------------------


@pytest.mark.parametrize(
    "message",
    [
        # Transient state, not a fact about the setup.
        "The backend is broken.",
        "The tests are failing.",
        "The server crashed on port 8123.",
        "Port 8123 is down.",
        # Not yet decided.
        "We might move the backend to port 8123.",
        "I'm thinking of using port 8123.",
        "Should we use port 8123?",
        # Historical, not current.
        "The backend was on port 8000 yesterday.",
        "We used to use port 8000.",
        # Questions.
        "What port does the backend use?",
        "Is the backend on port 8123?",
        # Nothing durable at all.
        "Thanks!",
        "",
        "   ",
    ],
)
def test_nothing_is_offered_for_these(message: str) -> None:
    assert suggest(message) is None


def test_a_suggestion_is_only_ever_a_suggestion() -> None:
    """It carries no id and no status: it is not a memory until save_memory
    runs, which is CONFIRM, which means the user sees it first."""
    suggestion = suggest("We're using port 8123 for the backend now.")

    payload = suggestion.to_dict()
    assert set(payload) == {"type", "key", "value", "reason"}
    assert "id" not in payload
    assert "status" not in payload


def test_the_reason_is_phrased_for_the_user() -> None:
    suggestion = suggest("We're using port 8123 for the backend now.")

    assert suggestion.reason == "you said port 8123"
