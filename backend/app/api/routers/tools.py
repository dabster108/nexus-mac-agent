"""Tool discovery.

Information only. Tools are executed by the agent through the tool registry and
MCP — never directly from an HTTP request.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, status

from app.api.deps import RunnerDep
from app.api.schemas import ErrorResponse, ToolListResponse, ToolResponse

router = APIRouter(prefix="/api/tools", tags=["tools"])


@router.get(
    "",
    response_model=ToolListResponse,
    summary="List available tools",
    description=(
        "Tools discovered through the registry, with the permission level that "
        "governs them. This endpoint cannot execute anything."
    ),
)
async def list_tools(runner: RunnerDep) -> ToolListResponse:
    definitions = await runner.list_tools()
    return ToolListResponse(
        tools=[ToolResponse.from_definition(definition) for definition in definitions]
    )


@router.get(
    "/{tool_name}",
    response_model=ToolResponse,
    summary="Get one tool",
    description="Metadata for a single tool. Information only — no execution.",
    responses={404: {"model": ErrorResponse, "description": "Unknown tool"}},
)
async def get_tool(tool_name: str, runner: RunnerDep) -> ToolResponse:
    for definition in await runner.list_tools():
        if definition.name == tool_name:
            return ToolResponse.from_definition(definition)
    raise HTTPException(
        status_code=status.HTTP_404_NOT_FOUND, detail=f"Unknown tool '{tool_name}'."
    )
