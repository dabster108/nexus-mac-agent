"""Shared FastAPI dependencies.

Routes depend on these service objects rather than constructing anything
themselves, which keeps the route bodies thin.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends

from app.agent.approvals import ApprovalBroker, get_approval_broker
from app.agent.runner import AgentRunner, get_agent_runner
from app.agent.tasks import TaskStore, get_task_store
from app.core.config import Settings, get_settings
from app.mcp.registry import MCPServerRegistry, get_mcp_registry
from app.models.router import ModelRouter, get_model_router

RunnerDep = Annotated[AgentRunner, Depends(get_agent_runner)]
TaskStoreDep = Annotated[TaskStore, Depends(get_task_store)]
BrokerDep = Annotated[ApprovalBroker, Depends(get_approval_broker)]
SettingsDep = Annotated[Settings, Depends(get_settings)]
ModelRouterDep = Annotated[ModelRouter, Depends(get_model_router)]
MCPRegistryDep = Annotated[MCPServerRegistry, Depends(get_mcp_registry)]

__all__ = [
    "BrokerDep",
    "MCPRegistryDep",
    "ModelRouterDep",
    "RunnerDep",
    "SettingsDep",
    "TaskStoreDep",
]
