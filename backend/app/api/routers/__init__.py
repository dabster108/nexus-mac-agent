"""One router per API group, mounted in :mod:`app.main`."""

from app.api.routers import chat, health, mcp, models, permissions, tasks, tools

#: Mount order determines the order of the groups in /docs.
ALL_ROUTERS = (
    health.router,
    chat.router,
    tasks.router,
    tools.router,
    permissions.router,
    mcp.router,
    models.router,
)

__all__ = ["ALL_ROUTERS", "chat", "health", "mcp", "models", "permissions", "tasks", "tools"]
