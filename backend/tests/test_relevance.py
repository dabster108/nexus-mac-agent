"""Deterministic relevance: which memories are worth the tokens.

The point of scoring rather than searching is that every inclusion can be
explained, so these tests assert on *why* a memory scored as well as whether
it did.
"""

from __future__ import annotations

import pytest

from app.context import relevance


def memory(**kwargs) -> dict:
    base = {
        "id": "mem_1",
        "type": "FACT",
        "key": "thing",
        "value": {},
        "confidence_level": "MEDIUM",
        "stale": False,
    }
    base.update(kwargs)
    return base


# --- keywords --------------------------------------------------------------


def test_keywords_drop_filler_words() -> None:
    words = relevance.keywords("What do you remember about my nexus backend?")

    assert "nexus" in words
    assert "backend" in words
    for filler in ("what", "you", "remember", "about", "my"):
        assert filler not in words


def test_named_paths_are_extracted_but_never_invented() -> None:
    assert relevance.named_paths("Inspect /Users/me/nexus please") == ["/Users/me/nexus"]
    assert relevance.named_paths("Inspect my nexus project") == []


# --- scoring ---------------------------------------------------------------


def test_an_exact_key_match_outranks_everything_else() -> None:
    exact = relevance.score_memory(
        memory(key="nexus"),
        words=["nexus"], paths=[], active_workspace=None, intent="GENERAL",
    )
    partial = relevance.score_memory(
        memory(key="nexus_backend_port"),
        words=["nexus"], paths=[], active_workspace=None, intent="GENERAL",
    )

    assert exact.score > partial.score
    assert "named in the request" in relevance.explain(exact)


def test_a_memory_for_the_active_workspace_is_relevant_without_a_keyword() -> None:
    scored = relevance.score_memory(
        memory(key="port", value={"path": "/x/nexus", "port": 8123}),
        words=["running"],
        paths=[],
        active_workspace="/x/nexus",
        intent="GENERAL",
    )

    assert scored.relevant
    assert "active workspace" in relevance.explain(scored)


def test_an_unrelated_memory_scores_below_the_threshold() -> None:
    scored = relevance.score_memory(
        memory(key="dentist_appointment", value={"when": "tuesday"}),
        words=["nexus", "backend"],
        paths=[],
        active_workspace="/x/nexus",
        intent="GENERAL",
    )

    assert not scored.relevant


def test_recency_alone_never_makes_a_memory_relevant() -> None:
    """Otherwise the newest memory is always in the prompt, whatever it says."""
    scored = relevance.score_memory(
        memory(key="unrelated", age_days=0, confidence_level="HIGH"),
        words=["nexus"], paths=[], active_workspace=None, intent="GENERAL",
    )

    assert not scored.relevant


def test_a_stale_memory_is_penalised_but_can_still_surface() -> None:
    """It has to be reportable as out of date, so it is not simply dropped."""
    fresh = relevance.score_memory(
        memory(key="nexus", value={"path": "/x"}),
        words=["nexus"], paths=[], active_workspace=None, intent="GENERAL",
    )
    stale = relevance.score_memory(
        memory(key="nexus", value={"path": "/x"}, stale=True),
        words=["nexus"], paths=[], active_workspace=None, intent="GENERAL",
    )

    assert stale.score < fresh.score
    assert stale.relevant


def test_intent_nudges_the_types_that_matter_for_it() -> None:
    for_continue = relevance.score_memory(
        memory(type="TASK_CONTEXT", key="nexus"),
        words=["nexus"], paths=[], active_workspace=None, intent="CONTINUE",
    )
    for_general = relevance.score_memory(
        memory(type="TASK_CONTEXT", key="nexus"),
        words=["nexus"], paths=[], active_workspace=None, intent="GENERAL",
    )

    assert for_continue.score > for_general.score


# --- ranking ---------------------------------------------------------------


def test_rank_orders_by_score_and_drops_the_irrelevant() -> None:
    memories = [
        memory(id="a", key="dentist"),
        memory(id="b", key="nexus_port", value={"port": 8123}),
        memory(id="c", key="nexus"),
    ]

    ranked = relevance.rank(memories, message="what port does nexus use?", limit=10)

    assert [item.memory["id"] for item in ranked] == ["c", "b"]


def test_recall_bypasses_scoring_entirely() -> None:
    """"What do you remember?" is not a question about a topic."""
    memories = [memory(id="a", key="dentist"), memory(id="b", key="groceries")]

    ranked = relevance.rank(memories, message="what do you remember?", intent="RECALL")

    assert {item.memory["id"] for item in ranked} == {"a", "b"}


def test_rank_respects_its_limit() -> None:
    memories = [memory(id=f"m{i}", key=f"nexus_{i}") for i in range(20)]

    assert len(relevance.rank(memories, message="nexus", limit=5)) == 5


@pytest.mark.parametrize("value", [None, "a string", 42, []])
def test_scoring_survives_an_odd_value_shape(value) -> None:
    """Memory values are user-supplied objects; scoring must not assume a dict."""
    scored = relevance.score_memory(
        memory(value=value),
        words=["nexus"], paths=[], active_workspace="/x", intent="GENERAL",
    )

    assert isinstance(scored.score, float)
