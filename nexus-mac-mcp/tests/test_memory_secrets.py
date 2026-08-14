"""The secret detector: what must never enter the memory store."""

from __future__ import annotations

import pytest

from nexus_mac_mcp.core.memory_secrets import (
    SecretDetectedError,
    assert_no_secret,
    find_secret,
)

# --- must always be refused -------------------------------------------


@pytest.mark.parametrize(
    ("key", "value"),
    [
        ("groq_key", {"value": "gsk_abcdefghijklmnopqrstuvwxyz123456"}),
        ("openai_key", {"value": "sk-abcdefghijklmnopqrstuvwxyz1234567890"}),
        ("github_pat", {"value": "ghp_abcdefghijklmnopqrstuvwxyz1234"}),
        ("aws_key", {"value": "AKIAABCDEFGHIJKLMNOP"}),
        ("google_key", {"value": "AIzaSyAbCdEfGhIjKlMnOpQrStUvWxYz1234567"}),
        ("slack_token", {"value": "xoxb-1234567890-abcdefghijklmnop"}),
        ("jwt", {"value": "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxIn0.dozjgNryP4J3jVmNHl0w5N_XgL0n3I9PlFUP0THsR8U"}),
        ("ssh_key", {"value": "-----BEGIN OPENSSH PRIVATE KEY-----\nb3BlbnNzaA\n-----END OPENSSH PRIVATE KEY-----"}),
        ("env_dump", {"value": "GROQ_API_KEY=gsk_abcdefghijklmnopqrstuvwxyz123456"}),
        ("note", {"value": "my password is hunter2hunter2"}),
        ("note2", {"value": "the api key: gsk_abcdefghijklmnopqrstuvwxyz123456"}),
    ],
)
def test_secret_values_are_detected(key: str, value: dict) -> None:
    with pytest.raises(SecretDetectedError, match="credential"):
        assert_no_secret(key, value)


@pytest.mark.parametrize(
    "field",
    [
        "api_key", "apikey", "password", "passwd", "secret", "token",
        "access_key", "private_key", "credential", "auth", "cookie",
        "client_secret", "session_id", "PASSWORD", "API_KEY",
    ],
)
def test_secret_looking_field_names_are_refused_regardless_of_value(field: str) -> None:
    with pytest.raises(SecretDetectedError):
        assert_no_secret("note", {field: "anything"})


def test_a_secret_key_as_the_memory_key_itself_is_refused() -> None:
    with pytest.raises(SecretDetectedError, match="credential name"):
        assert_no_secret("api_key", {"value": "whatever"})


def test_a_nested_secret_is_found() -> None:
    with pytest.raises(SecretDetectedError):
        assert_no_secret(
            "config", {"settings": {"auth": {"token": "gsk_abcdefghijklmnopqrstuvwxyz123456"}}}
        )


def test_a_secret_inside_a_list_is_found() -> None:
    with pytest.raises(SecretDetectedError):
        assert_no_secret("notes", {"lines": ["fine", "gsk_abcdefghijklmnopqrstuvwxyz123456"]})


# --- must not be refused (no false positives on ordinary facts) -----------


@pytest.mark.parametrize(
    ("key", "value"),
    [
        ("nexus_project", {"name": "NEXUS", "path": "~/Documents/nexus"}),
        ("backend", {"framework": "FastAPI", "port": 8000}),
        ("editor_preference", {"name": "vim"}),
        ("workflow", {"steps": ["pytest", "npm run build"]}),
        ("note", {"text": "the backend runs on port 8000"}),
        ("note2", {"text": "keys are in the top drawer"}),  # "key" alone, no marker match
        ("commit", {"hash": "a1b2c3d4"}),
    ],
)
def test_ordinary_facts_are_not_flagged(key: str, value: dict) -> None:
    assert_no_secret(key, value)  # must not raise
    assert find_secret(value) is None


def test_find_secret_returns_none_for_plain_strings() -> None:
    assert find_secret("just some ordinary text") is None


def test_find_secret_returns_none_for_empty_input() -> None:
    assert find_secret({}) is None
    assert find_secret([]) is None
    assert find_secret("") is None
