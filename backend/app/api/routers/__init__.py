"""One router per API group, mounted in :mod:`app.main`."""

from app.api.routers import (
    chat,
    context,
    health,
    mcp,
    memory,
    models,
    observations,
    permissions,
    tasks,
    tools,
)

#: Mount order determines the order of the groups in /docs.
ALL_ROUTERS = (
    health.router,
    chat.router,
    tasks.router,
    tools.router,
    permissions.router,
    context.router,
    memory.router,
    observations.router,
    mcp.router,
    models.router,
)

__all__ = [
    "ALL_ROUTERS",
    "chat",
    "context",
    "health",
    "mcp",
    "memory",
    "models",
    "observations",
    "permissions",
    "tasks",
    "tools",
]
