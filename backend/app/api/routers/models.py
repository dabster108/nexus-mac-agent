"""Model provider status.

Reports whether each provider is configured. Never reports the credential
itself.
"""

from __future__ import annotations

from fastapi import APIRouter

from app.api.deps import ModelRouterDep, SettingsDep
from app.api.schemas import ModelListResponse, ModelProviderResponse
from app.core.config import SUPPORTED_PROVIDERS

router = APIRouter(prefix="/api", tags=["models"])


@router.get(
    "/models",
    response_model=ModelListResponse,
    summary="List model providers",
    description=(
        "`available` means an API key and a model identifier are both "
        "configured for that provider. Keys are never returned."
    ),
)
async def list_models(
    router_: ModelRouterDep, settings: SettingsDep
) -> ModelListResponse:
    available = set(router_.available_providers())
    return ModelListResponse(
        providers=[
            ModelProviderResponse(
                name=name,
                available=name in available,
                model=settings.model_for(name),
            )
            for name in SUPPORTED_PROVIDERS
        ],
        default=router_.default_provider_name,
    )
