"""Liveness."""

from __future__ import annotations

from fastapi import APIRouter

from app.api.deps import SettingsDep
from app.api.schemas import HealthResponse

router = APIRouter(tags=["health"])


@router.get(
    "/health",
    response_model=HealthResponse,
    summary="Health check",
    description="Liveness probe. Does not touch the model, MCP or any tool.",
)
async def health(settings: SettingsDep) -> HealthResponse:
    return HealthResponse(status="ok", service=settings.service_name)
