"""Configuration loading."""

from __future__ import annotations

import pytest

from app.core.config import SUPPORTED_PROVIDERS, Settings, build_settings


def _clear(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in (
        "GROQ_API_KEY",
        "MISTRAL_API_KEY",
        "DEFAULT_MODEL_PROVIDER",
        "GROQ_MODEL",
        "MISTRAL_MODEL",
        "BACKEND_HOST",
        "BACKEND_PORT",
        "LOG_LEVEL",
        "AGENT_MAX_ITERATIONS",
    ):
        monkeypatch.delenv(name, raising=False)


def test_defaults_are_local_and_groq(monkeypatch: pytest.MonkeyPatch) -> None:
    _clear(monkeypatch)
    monkeypatch.setattr("app.core.config.load_dotenv", lambda *a, **k: False)

    settings = build_settings()

    assert settings.backend_host == "127.0.0.1"
    assert settings.backend_port == 8000
    assert settings.default_model_provider == "groq"
    assert settings.service_name == "nexus-agent"


def test_env_is_read_through_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    _clear(monkeypatch)
    monkeypatch.setattr("app.core.config.load_dotenv", lambda *a, **k: False)
    monkeypatch.setenv("GROQ_API_KEY", "gk-123")
    monkeypatch.setenv("DEFAULT_MODEL_PROVIDER", "mistral")
    monkeypatch.setenv("MISTRAL_MODEL", "some-model")
    monkeypatch.setenv("BACKEND_PORT", "9100")

    settings = build_settings()

    assert settings.groq_api_key == "gk-123"
    assert settings.default_model_provider == "mistral"
    assert settings.model_for("mistral") == "some-model"
    assert settings.backend_port == 9100


def test_model_identifiers_are_not_invented(monkeypatch: pytest.MonkeyPatch) -> None:
    _clear(monkeypatch)
    monkeypatch.setattr("app.core.config.load_dotenv", lambda *a, **k: False)

    settings = build_settings()

    assert settings.groq_model is None
    assert settings.mistral_model is None


def test_unknown_provider_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    _clear(monkeypatch)
    monkeypatch.setattr("app.core.config.load_dotenv", lambda *a, **k: False)
    monkeypatch.setenv("DEFAULT_MODEL_PROVIDER", "openai")

    with pytest.raises(ValueError, match="DEFAULT_MODEL_PROVIDER"):
        build_settings()


def test_supported_providers(settings: Settings) -> None:
    assert SUPPORTED_PROVIDERS == ("groq", "mistral")
    assert settings.api_key_for("groq") == "test-groq-key"
    assert settings.api_key_for("unknown") is None
