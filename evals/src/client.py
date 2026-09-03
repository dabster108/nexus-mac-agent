"""Langfuse client singleton for the eval harness."""

from __future__ import annotations

from langfuse import Langfuse

from src.config import EvalConfig

_instance: Langfuse | None = None


def get_langfuse(config: EvalConfig | None = None) -> Langfuse:
    """Return (and cache) a Langfuse client."""
    global _instance  # noqa: PLW0603
    if _instance is not None:
        return _instance

    cfg = config or EvalConfig.from_env()
    _instance = Langfuse(
        secret_key=cfg.langfuse_secret_key,
        public_key=cfg.langfuse_public_key,
        host=cfg.langfuse_host,
    )
    return _instance


def flush() -> None:
    """Flush any pending Langfuse events (call at harness exit)."""
    if _instance is not None:
        _instance.flush()
