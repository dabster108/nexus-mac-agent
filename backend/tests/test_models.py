"""Model provider selection and the provider-neutral interface."""

from __future__ import annotations

import pytest

from app.core.config import Settings
from app.core.errors import ConfigurationError
from app.models.base import ToolSpec, classify_provider_error, loads_arguments
from app.models.groq import GroqProvider
from app.models.mistral import MistralProvider
from app.models.router import ModelRouter


def test_default_provider_is_groq(settings: Settings) -> None:
    router = ModelRouter(settings)

    provider = router.get_provider()

    assert provider.name == "groq"
    assert provider.model == "test-groq-model"


def test_provider_can_be_overridden_per_request(settings: Settings) -> None:
    router = ModelRouter(settings)

    assert router.get_provider("mistral").name == "mistral"


def test_provider_instances_are_reused(settings: Settings) -> None:
    router = ModelRouter(settings)

    assert router.get_provider("groq") is router.get_provider("groq")


def test_unknown_provider_raises(settings: Settings) -> None:
    router = ModelRouter(settings)

    with pytest.raises(ConfigurationError, match="Unknown model provider"):
        router.get_provider("openai")


def test_available_providers_need_key_and_model(settings: Settings) -> None:
    router = ModelRouter(settings)
    assert router.available_providers() == ("groq", "mistral")

    partial = ModelRouter(replace_model(settings, mistral_model=None))
    assert partial.available_providers() == ("groq",)


def replace_model(settings: Settings, **changes: object) -> Settings:
    import dataclasses

    return dataclasses.replace(settings, **changes)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    ("provider_cls", "kwargs", "expected"),
    [
        (GroqProvider, {"api_key": None, "model": "m"}, "GROQ_API_KEY"),
        (GroqProvider, {"api_key": "k", "model": None}, "GROQ_MODEL"),
        (MistralProvider, {"api_key": None, "model": "m"}, "MISTRAL_API_KEY"),
        (MistralProvider, {"api_key": "k", "model": None}, "MISTRAL_MODEL"),
    ],
)
def test_missing_credentials_fail_loudly(
    provider_cls: type, kwargs: dict[str, object], expected: str
) -> None:
    with pytest.raises(ConfigurationError, match=expected):
        provider_cls(**kwargs)


def test_tool_spec_becomes_an_openai_function() -> None:
    spec = ToolSpec(
        name="battery_status",
        description="Battery",
        input_schema={"type": "object", "properties": {}},
    )

    assert spec.to_openai_tool() == {
        "type": "function",
        "function": {
            "name": "battery_status",
            "description": "Battery",
            "parameters": {"type": "object", "properties": {}},
        },
    }


def test_malformed_tool_arguments_do_not_crash() -> None:
    assert loads_arguments("not json") == {}
    assert loads_arguments('{"a": 1}') == {"a": 1}
    assert loads_arguments(None) == {}


# --- provider error classification (Phase 9) ------------------------------


class _VendorError(Exception):
    """Stands in for a Groq/Mistral SDK error, which carries a status code."""

    def __init__(self, message: str, status_code: int | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code


ORG_ID = "org_01jqh2h6gefgw97c7vaj290k4t"

RATE_LIMIT = _VendorError(
    "Error code: 413 - {'error': {'message': 'Request too large for model "
    f"`llama-3.1-8b-instant` in organization `{ORG_ID}` on tokens per minute "
    "(TPM): Limit 6000, Requested 6774', 'code': 'rate_limit_exceeded'}}",
    413,
)
MALFORMED_TOOL_CALL = _VendorError(
    "Error code: 400 - tool call validation failed: parameters for tool "
    "git_status did not match schema: missing properties: 'path'",
    400,
)


@pytest.mark.parametrize(
    ("exc", "category", "expected_in_message"),
    [
        (RATE_LIMIT, "rate_limit", "rate limiting"),
        (MALFORMED_TOOL_CALL, "tool_call", "malformed"),
        (_VendorError("Error code: 401 - invalid_api_key", 401), "auth", "API key"),
        (_VendorError("Error code: 404 - model not found", 404), "model_not_found", "model"),
        (_VendorError("Connection timed out"), "connectivity", "could not be reached"),
        (_VendorError("kaboom"), "unknown", "request failed"),
    ],
)
def test_provider_failures_are_classified_accurately(
    exc: Exception, category: str, expected_in_message: str
) -> None:
    """Phase 9: every failure used to read "could not be reached", which sent
    people looking at their network when the cause was a rate limit or a
    malformed tool call."""
    message, found = classify_provider_error("Groq", "GROQ_API_KEY", exc)

    assert found == category
    assert expected_in_message in message


def test_a_rate_limit_is_not_reported_as_connectivity() -> None:
    message, category = classify_provider_error("Groq", "GROQ_API_KEY", RATE_LIMIT)

    assert category == "rate_limit"
    assert "could not be reached" not in message


def test_vendor_account_details_never_reach_the_user_message() -> None:
    """The vendor text names the organisation; that belongs in the log only."""
    message, _ = classify_provider_error("Groq", "GROQ_API_KEY", RATE_LIMIT)

    assert ORG_ID not in message
    assert "llama-3.1-8b-instant" not in message


def test_the_named_env_var_matches_the_provider() -> None:
    _, _ = classify_provider_error("Mistral", "MISTRAL_API_KEY", RATE_LIMIT)
    message, _ = classify_provider_error(
        "Mistral", "MISTRAL_API_KEY", _VendorError("unauthorized", 401)
    )

    assert "MISTRAL_API_KEY" in message
    assert "GROQ_API_KEY" not in message
