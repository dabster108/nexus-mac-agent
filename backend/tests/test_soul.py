"""Tests for soul.md loading."""

from __future__ import annotations

from app.agent.nodes import DEFAULT_SYSTEM_PROMPT, SYSTEM_PROMPT
from app.agent.soul import SOUL_PATH, agent_system_prompt, load_soul


def test_soul_md_exists_and_loads() -> None:
    assert SOUL_PATH.is_file()
    soul = load_soul()
    assert "Voice" in soul
    assert "First contact" in soul


def test_default_system_prompt_includes_soul_and_rules() -> None:
    soul = load_soul()
    assert soul in DEFAULT_SYSTEM_PROMPT
    assert SYSTEM_PROMPT in DEFAULT_SYSTEM_PROMPT


def test_context_is_appended_after_rules() -> None:
    prompt = agent_system_prompt(SYSTEM_PROMPT, context_block="Workspace: ~/Projects/foo")
    assert load_soul() in prompt
    assert SYSTEM_PROMPT in prompt
    assert "Workspace: ~/Projects/foo" in prompt
    assert prompt.index(load_soul()) < prompt.index(SYSTEM_PROMPT)
    assert prompt.index(SYSTEM_PROMPT) < prompt.index("Workspace: ~/Projects/foo")
