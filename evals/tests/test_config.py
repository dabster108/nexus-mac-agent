"""Config and dry-run behaviour."""

from __future__ import annotations

import pytest

from src.config import EvalConfig


def test_dry_run_does_not_require_langfuse(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("LANGFUSE_SECRET_KEY", raising=False)
    monkeypatch.delenv("LANGFUSE_PUBLIC_KEY", raising=False)
    monkeypatch.setenv("NEXUS_API_URL", "http://127.0.0.1:8000")

    config = EvalConfig.from_env(dry_run=True)
    assert config.dry_run is True
    assert config.langfuse_enabled is False
    config.require_langfuse()  # must not raise


def test_live_run_requires_real_keys(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LANGFUSE_SECRET_KEY", "sk-lf-...")
    monkeypatch.setenv("LANGFUSE_PUBLIC_KEY", "pk-lf-...")

    config = EvalConfig.from_env(dry_run=False)
    assert config.langfuse_enabled is False
    with pytest.raises(RuntimeError, match="--dry-run"):
        config.require_langfuse()


def test_live_run_with_keys(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LANGFUSE_SECRET_KEY", "sk-lf-real")
    monkeypatch.setenv("LANGFUSE_PUBLIC_KEY", "pk-lf-real")

    config = EvalConfig.from_env(dry_run=False)
    assert config.langfuse_enabled is True
    config.require_langfuse()
