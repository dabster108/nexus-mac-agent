"""Model provider selection and the provider-neutral interface."""

from __future__ import annotations

import pytest

from app.core.config import Settings
from app.core.errors import ConfigurationError
from app.models.base import ToolSpec, loads_arguments
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
