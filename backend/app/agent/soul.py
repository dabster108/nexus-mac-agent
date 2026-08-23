"""Load the agent's personality from soul.md.

The rules in :mod:`app.agent.nodes` say what NEXUS must do. ``soul.md`` says
how it should feel while doing it. Both are injected into the system prompt;
neither replaces permission checks, verification, or tool policy.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
SOUL_PATH = REPO_ROOT / "soul.md"


@lru_cache
def load_soul() -> str:
    """The soul document, or empty if it is missing."""
    if not SOUL_PATH.is_file():
        return ""
    return SOUL_PATH.read_text(encoding="utf-8").strip()


def agent_system_prompt(rules: str, *, context_block: str = "") -> str:
    """Rules + soul + optional per-request context."""
    soul = load_soul()
    parts = [part for part in (soul, rules, context_block) if part]
    return "\n\n---\n\n".join(parts)
