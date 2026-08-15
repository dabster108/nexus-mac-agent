"""Intent classification, and the context each intent is allowed to gather.

The behavioural requirement from §12 is the last test in this file: asking for
the battery must not cause a workspace scan.
"""

from __future__ import annotations

import pytest

from app.context.intent import Intent, classify, plan_for


@pytest.mark.parametrize(
    "message",
    [
        "Continue where I left off.",
        "continue my nexus work",
        "Resume what I was doing.",
        "Pick up where we left off",
        "carry on with the backend",
    ],
)
def test_continue_phrasings(message: str) -> None:
    assert classify(message) is Intent.CONTINUE


@pytest.mark.parametrize(
    "message",
    [
        "What changed recently?",
        "What did I change?",
        "what's changed since yesterday",
        "Show me my recent changes",
    ],
)
def test_what_changed_phrasings(message: str) -> None:
    assert classify(message) is Intent.WHAT_CHANGED


@pytest.mark.parametrize(
    "message",
    [
        "What am I working on?",
        "What was I doing?",
        "Where was I working?",
        "What project am I in?",
    ],
)
def test_orientation_phrasings(message: str) -> None:
    assert classify(message) is Intent.ORIENT


@pytest.mark.parametrize(
    "message",
    [
        "What do you remember?",
        "What do you remember about this project?",
        "Show me what you remember",
    ],
)
def test_recall_phrasings(message: str) -> None:
    assert classify(message) is Intent.RECALL


@pytest.mark.parametrize(
    "message",
    ["What is my battery percentage?", "Open Calculator", "", "   "],
)
def test_everything_else_is_general(message: str) -> None:
    assert classify(message) is Intent.GENERAL


# --- what each intent may gather -------------------------------------------


def test_a_simple_question_does_no_filesystem_work() -> None:
    """§12: "what's my battery?" must not trigger a workspace scan."""
    plan = plan_for("What is my battery percentage?")

    assert plan.workspace is False
    assert plan.git_history is False
    assert plan.processes is False


def test_continue_gathers_the_full_picture() -> None:
    plan = plan_for("Continue where I left off.")

    assert plan.memories and plan.workspace and plan.git_history and plan.processes


def test_what_changed_reaches_for_git_not_memory() -> None:
    """Answering from remembered history is how fabricated history happens."""
    plan = plan_for("What changed since yesterday?")

    assert plan.git_history is True
    assert plan.memories is False


def test_recall_touches_nothing_but_memory() -> None:
    plan = plan_for("What do you remember?")

    assert plan.memories is True
    assert not (plan.workspace or plan.git_history or plan.processes or plan.machine)
