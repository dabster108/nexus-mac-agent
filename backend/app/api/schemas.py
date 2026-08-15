"""Request/response models.

These define exactly what crosses the boundary to the frontend. API keys and
other settings values are never part of any schema here.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

from app.agent.approvals import ApprovalRequest
from app.agent.tasks import TaskRecord
from app.mcp.registry import MCPServerStatus
from app.tools.registry import ToolDefinition

#: A generous ceiling on pre-approved tool names. There are 23 tools; a list
#: far longer than that is a malformed client, not a real request.
MAX_APPROVED_TOOLS = 64

# --- health ----------------------------------------------------------------


class HealthResponse(BaseModel):
    status: str = Field(default="ok", examples=["ok"])
    service: str = Field(default="nexus-agent", examples=["nexus-agent"])


# --- chat ------------------------------------------------------------------


class ChatRequest(BaseModel):
    message: str = Field(
        min_length=1,
        max_length=8000,
        examples=["What is my battery percentage?"],
    )
    provider: Literal["groq", "mistral"] | None = Field(
        default=None,
        description="Override DEFAULT_MODEL_PROVIDER for this request ('groq' or 'mistral').",
    )
    approved_tools: list[str] = Field(
        default_factory=list,
        max_length=MAX_APPROVED_TOOLS,
        description=(
            "Tools pre-approved for this request. CONFIRM tools not listed here "
            "raise a permission request instead. Pre-approval covers the whole "
            "task and any arguments, so it is the caller's decision to make "
            "per request; RESTRICTED tools can never be pre-approved."
        ),
    )


class ChatResponse(BaseModel):
    """Acknowledgement that the request was accepted.

    The agent runs in the background; follow it on ``WS /api/ws`` or
    ``GET /api/tasks/{task_id}``.
    """

    task_id: str = Field(examples=["task_9505279cbf074222b6d0db9588962dba"])
    status: str = Field(default="started", examples=["started"])


# --- tasks -----------------------------------------------------------------


class ErrorPayload(BaseModel):
    code: str = Field(examples=["TOOL_ERROR"])
    message: str


class ErrorResponse(BaseModel):
    """The body returned for every 4xx/5xx the backend raises deliberately."""

    error: ErrorPayload


class PermissionRequestPayload(BaseModel):
    tool: str
    permission: str
    reason: str
    arguments: dict[str, Any] = Field(default_factory=dict)


class TaskSummary(BaseModel):
    task_id: str
    status: str = Field(examples=["completed"])
    request: str
    message: str | None = Field(
        default=None, description="Latest user-facing message for this task."
    )
    created_at: str
    completed_at: str | None = None

    @classmethod
    def from_record(cls, record: TaskRecord) -> TaskSummary:
        return cls.model_validate(record.to_summary())


class TaskResponse(TaskSummary):
    response: str | None = Field(default=None, description="The agent's final answer.")
    events: list[dict[str, Any]] = Field(default_factory=list)
    error: ErrorPayload | None = None
    permission_request: PermissionRequestPayload | None = None
    updated_at: str

    @classmethod
    def from_record(cls, record: TaskRecord) -> TaskResponse:
        return cls.model_validate(record.to_dict())


class TaskListResponse(BaseModel):
    tasks: list[TaskSummary]


class TaskStatusResponse(BaseModel):
    """Minimal state report, used by the cancel endpoint."""

    task_id: str
    status: str = Field(examples=["cancelled"])


# --- tools -----------------------------------------------------------------


class ToolResponse(BaseModel):
    name: str = Field(examples=["battery_status"])
    description: str
    source: str = Field(examples=["nexus-mac"])
    permission: str = Field(examples=["SAFE"])
    input_schema: dict[str, Any] = Field(default_factory=dict)

    @classmethod
    def from_definition(cls, definition: ToolDefinition) -> ToolResponse:
        return cls.model_validate(definition.to_public_dict())


class ToolListResponse(BaseModel):
    tools: list[ToolResponse]


# --- permissions -----------------------------------------------------------


class PermissionRequestResponse(BaseModel):
    """A tool call waiting on the user's decision."""

    request_id: str = Field(examples=["perm_2f6c1b9a4d3e5f70"])
    task_id: str
    tool: str = Field(examples=["open_application"])
    permission: str = Field(examples=["CONFIRM"])
    description: str = Field(
        examples=["Open an installed macOS application by name (application: Safari)"]
    )
    arguments: dict[str, Any] = Field(
        default_factory=dict,
        description="Shown so the user can see what they are approving.",
    )
    status: str = Field(examples=["pending"])
    created_at: str
    resolved_at: str | None = None

    @classmethod
    def from_request(cls, request: ApprovalRequest) -> PermissionRequestResponse:
        return cls.model_validate(request.to_dict())


class PermissionListResponse(BaseModel):
    requests: list[PermissionRequestResponse]


class PermissionResponse(BaseModel):
    """The outcome of approving or denying a request."""

    request_id: str
    status: str = Field(examples=["approved"])


# --- mcp -------------------------------------------------------------------


class MCPServerResponse(BaseModel):
    name: str = Field(examples=["nexus-mac"])
    status: str = Field(examples=["connected"])
    tools: int = Field(examples=[2])
    reason: str | None = Field(
        default=None, description="Why the server is unreachable, when it is."
    )

    @classmethod
    def from_status(cls, status: MCPServerStatus) -> MCPServerResponse:
        return cls.model_validate(status.to_public_dict())


class MCPServerListResponse(BaseModel):
    servers: list[MCPServerResponse]


# --- models ----------------------------------------------------------------


class ModelProviderResponse(BaseModel):
    name: str = Field(examples=["groq"])
    available: bool = Field(
        description="Whether an API key and model identifier are both configured."
    )
    model: str | None = Field(
        default=None, description="The configured model id. Never a credential."
    )


class ModelListResponse(BaseModel):
    providers: list[ModelProviderResponse]
    default: str = Field(examples=["groq"])


# --- context / memory (Phase 10) -------------------------------------------


class MemoryResponse(BaseModel):
    """One remembered fact, as the memory panel shows it.

    Mirrors the MCP tool's public shape. Deliberately not the database row:
    no internal status column, no storage detail (§21).
    """

    id: str = Field(examples=["mem_07f9e4aa0410"])
    type: str = Field(examples=["PROJECT"])
    key: str = Field(examples=["nexus_project"])
    value: dict[str, Any] = Field(default_factory=dict)
    confidence_level: str = Field(default="MEDIUM", examples=["HIGH"])
    last_verified_at: str | None = None
    stale: bool = False
    conflict: str | None = None
    reasons: list[str] = Field(
        default_factory=list,
        description="Why this memory was considered relevant to a request.",
    )
    created_at: str | None = None
    updated_at: str | None = None


class MemoryListResponse(BaseModel):
    memories: list[MemoryResponse]
    count: int


class WorkspaceResponse(BaseModel):
    path: str
    verified: bool
    project_types: list[str] = Field(default_factory=list)
    is_git_repository: bool = False
    git_branch: str | None = None
    git_clean: bool | None = None
    changed_files: int | None = None
    recent_commits: list[str] = Field(default_factory=list)
    active: bool = False


class ProcessResponse(BaseModel):
    process_id: str
    name: str
    status: str = Field(examples=["RUNNING"])
    port: int | None = None
    working_directory: str | None = None


class MachineResponse(BaseModel):
    platform: str = Field(examples=["macOS"])
    architecture: str = Field(examples=["arm64"])
    cpu_count: int
    battery_percentage: int | None = None
    charging: bool | None = None


class ContextResponse(BaseModel):
    """The context panel's whole view. Every field comes from a real tool call."""

    intent: str = Field(default="GENERAL", examples=["ORIENT"])
    active_workspace: WorkspaceResponse | None = None
    workspaces: list[WorkspaceResponse] = Field(default_factory=list)
    memories: list[MemoryResponse] = Field(default_factory=list)
    processes: list[ProcessResponse] = Field(default_factory=list)
    machine: MachineResponse | None = None
    truncated: bool = False
