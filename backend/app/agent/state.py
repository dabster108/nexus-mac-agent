"""Typed LangGraph state.

Kept intentionally small: conversation, the tool activity for this run, the
events emitted, permission status and terminal condition. No memory system.
"""

from __future__ import annotations

import operator
from typing import Annotated, Any, NotRequired, TypedDict

from langchain_core.messages import AnyMessage, HumanMessage
from langgraph.graph import add_messages

from app.agent.events import ExecutionEvent


class ToolCallRecord(TypedDict):
    """A tool call the model asked for."""

    id: str
    name: str
    arguments: dict[str, Any]
    permission: str


class ToolResultRecord(TypedDict):
    """The outcome of one tool call."""

    id: str
    name: str
    success: bool
    content: str
    structured: NotRequired[Any]


class PermissionRequest(TypedDict):
    """An approval the user must grant before the run can continue."""

    tool: str
    permission: str
    reason: str
    arguments: dict[str, Any]


class ErrorInfo(TypedDict):
    code: str
    message: str


class AgentState(TypedDict):
    """State passed between graph nodes."""

    task_id: str
    user_request: str
    current_task: str | None
    messages: Annotated[list[AnyMessage], add_messages]
    tool_calls: Annotated[list[ToolCallRecord], operator.add]
    tool_results: Annotated[list[ToolResultRecord], operator.add]
    execution_events: Annotated[list[ExecutionEvent], operator.add]
    requires_permission: bool
    permission_request: PermissionRequest | None
    completed: bool
    error: ErrorInfo | None
    iterations: int


def initial_state(task_id: str, user_request: str) -> AgentState:
    """Build the state a run starts from."""
    return AgentState(
        task_id=task_id,
        user_request=user_request,
        current_task=user_request,
        messages=[HumanMessage(content=user_request)],
        tool_calls=[],
        tool_results=[],
        execution_events=[],
        requires_permission=False,
        permission_request=None,
        completed=False,
        error=None,
        iterations=0,
    )
