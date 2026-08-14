"""The mission-routing heuristic.

Deterministic and unit-testable on its own — no model call involved, which is
the point: an ordinary factual question must never pay for planning latency.
"""

from __future__ import annotations

import pytest

from app.mission.detection import looks_like_mission


@pytest.mark.parametrize(
    "message",
    [
        "Prepare my project for development.",
        "Check my project, run the tests, and tell me whether they pass.",
        "Start my backend and check whether it is healthy.",
        "Set up my development environment.",
        "Find out why my backend is not working.",
        "Why isn't my backend responding?",
        "Why is my backend down?",
        "Start the backend, then start the frontend, then check both.",
    ],
)
def test_messages_that_should_route_to_a_mission(message: str) -> None:
    assert looks_like_mission(message) is True


@pytest.mark.parametrize(
    "message",
    [
        "What is my battery percentage?",
        "Tell me about this Mac.",
        "Show me the Git status of this project.",
        "Open Visual Studio Code.",
        "Run the tests.",
        "Find my NEXUS project.",
        "Read my README.",
        "Inspect this project and tell me what it is.",
        "",
        "   ",
    ],
)
def test_ordinary_requests_stay_on_the_single_task_path(message: str) -> None:
    assert looks_like_mission(message) is False


def test_the_heuristic_is_case_insensitive() -> None:
    assert looks_like_mission("PREPARE MY PROJECT FOR DEVELOPMENT.") is True


def test_a_bare_mention_of_the_word_mission_routes_to_one() -> None:
    """Deliberately simple: any explicit mention of "mission" opts in."""
    assert looks_like_mission("Run this as a mission.") is True
