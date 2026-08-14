"""Model router.

Selects a :class:`~app.models.base.ModelProvider` by name, defaulting to
``DEFAULT_MODEL_PROVIDER``. Later this can grow task-complexity-based routing;
for v1 it is a straight lookup so the graph stays provider-agnostic.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from functools import lru_cache

from app.core.config import SUPPORTED_PROVIDERS, Settings, get_settings
from app.core.errors import ConfigurationError
from app.models.base import ModelProvider
from app.models.groq import GroqProvider
from app.models.mistral import MistralProvider

ProviderFactory = Callable[[Settings], ModelProvider]


def _build_groq(settings: Settings) -> ModelProvider:
    return GroqProvider(
        api_key=settings.groq_api_key,
        model=settings.groq_model,
        temperature=settings.model_temperature,
        timeout=settings.request_timeout_seconds,
    )


def _build_mistral(settings: Settings) -> ModelProvider:
    return MistralProvider(
        api_key=settings.mistral_api_key,
        model=settings.mistral_model,
        temperature=settings.model_temperature,
        timeout=settings.request_timeout_seconds,
    )


PROVIDER_FACTORIES: Mapping[str, ProviderFactory] = {
    "groq": _build_groq,
    "mistral": _build_mistral,
}


class ModelRouter:
    """Creates and caches providers for the configured backends."""

    def __init__(
        self,
        settings: Settings,
        factories: Mapping[str, ProviderFactory] | None = None,
    ) -> None:
        self._settings = settings
        self._factories = dict(factories or PROVIDER_FACTORIES)
        self._cache: dict[str, ModelProvider] = {}

    @property
    def default_provider_name(self) -> str:
        return self._settings.default_model_provider

    def available_providers(self) -> tuple[str, ...]:
        """Provider names that have both a key and a model configured."""
        return tuple(
            name
            for name in SUPPORTED_PROVIDERS
            if self._settings.api_key_for(name) and self._settings.model_for(name)
        )

    def get_provider(self, name: str | None = None) -> ModelProvider:
        provider_name = (name or self.default_provider_name).lower()
        if provider_name not in self._factories:
            raise ConfigurationError(
                f"Unknown model provider {provider_name!r}. "
                f"Supported providers: {', '.join(sorted(self._factories))}."
            )
        if provider_name not in self._cache:
            self._cache[provider_name] = self._factories[provider_name](self._settings)
        return self._cache[provider_name]


@lru_cache(maxsize=1)
def get_model_router() -> ModelRouter:
    return ModelRouter(get_settings())
