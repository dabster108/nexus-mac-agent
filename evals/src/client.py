"""Langfuse client for the eval harness (SDK v4).

Uses the observation API (`start_as_current_observation`). The old
``langfuse.trace()`` / ``.span()`` / ``.generation()`` surface was removed in
v3 and is not available in the installed SDK.
"""

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
        environment=cfg.langfuse_environment,
    )
    return _instance


def reset_langfuse() -> None:
    """Drop the cached client (tests / re-config)."""
    global _instance  # noqa: PLW0603
    if _instance is not None:
        _instance.shutdown()
    _instance = None


def check_auth(config: EvalConfig | None = None) -> bool:
    """Verify credentials against Langfuse. Raises on transport failure."""
    return get_langfuse(config).auth_check()


def flush() -> None:
    """Flush any pending Langfuse events (call at harness exit)."""
    if _instance is not None:
        _instance.flush()


def shutdown() -> None:
    """Flush and tear down the client."""
    global _instance  # noqa: PLW0603
    if _instance is not None:
        _instance.shutdown()
        _instance = None
