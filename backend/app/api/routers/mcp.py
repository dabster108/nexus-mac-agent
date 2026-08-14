"""MCP server status.

Read-only. Connection management stays backend-controlled — there are no
connect/disconnect endpoints on purpose.
"""

from __future__ import annotations

from fastapi import APIRouter

from app.api.deps import MCPRegistryDep
from app.api.schemas import MCPServerListResponse, MCPServerResponse

router = APIRouter(prefix="/api/mcp", tags=["mcp"])


@router.get(
    "/servers",
    response_model=MCPServerListResponse,
    summary="List MCP servers",
    description=(
        "Each configured server is contacted for real. An unreachable server is "
        "reported as disconnected with the reason attached."
    ),
)
async def list_servers(registry: MCPRegistryDep) -> MCPServerListResponse:
    statuses = await registry.probe()
    return MCPServerListResponse(
        servers=[MCPServerResponse.from_status(status) for status in statuses]
    )
