"""Bridge between MCP servers and the tool registry.

This is the only place where MCP concepts are translated into the neutral
``ToolDefinition`` / ``ToolResult`` vocabulary the agent understands.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from contextlib import AsyncExitStack
from dataclasses import dataclass
from functools import lru_cache
from typing import Any, Literal

from app.core.config import BACKEND_ROOT, Settings, get_settings
from app.core.errors import MCPError
from app.core.logging import get_logger, safe_keys
from app.mcp.client import MCPClient, MCPServerConfig, MCPSession
from app.tools.permissions import classify
from app.tools.registry import ToolDefinition, ToolResult

logger = get_logger(__name__)

#: Namespace a server can use in a tool's ``_meta`` to declare its permission
#: level, e.g. ``{"nexus": {"permission": "SAFE"}}``.
META_NAMESPACE = "nexus"


#: Longest approval-prompt template accepted from a server.
MAX_PROMPT_TEMPLATE = 200


def _namespaced(meta: dict[str, Any]) -> dict[str, Any]:
    namespaced = meta.get(META_NAMESPACE)
    return namespaced if isinstance(namespaced, dict) else {}


def _declared_permission(meta: dict[str, Any]) -> str | None:
    value = _namespaced(meta).get("permission")
    return value if isinstance(value, str) else None


def _declared_prompt(meta: dict[str, Any]) -> str | None:
    value = _namespaced(meta).get("prompt")
    if isinstance(value, str) and 0 < len(value) <= MAX_PROMPT_TEMPLATE:
        return value
    return None


@dataclass(frozen=True, slots=True)
class MCPServerStatus:
    """Live state of one configured MCP server."""

    name: str
    status: Literal["connected", "disconnected"]
    tools: int
    reason: str | None = None

    def to_public_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "name": self.name,
            "status": self.status,
            "tools": self.tools,
        }
        if self.reason:
            payload["reason"] = self.reason
        return payload


class MCPToolSource:
    """Exposes one MCP session as a :class:`~app.tools.registry.ToolSource`."""

    def __init__(self, session: MCPSession) -> None:
        self._session = session

    @property
    def name(self) -> str:
        return self._session.server_name

    async def list_tools(self) -> Sequence[ToolDefinition]:
        definitions: list[ToolDefinition] = []
        for tool in await self._session.list_tools():
            permission = classify(tool.name, _declared_permission(tool.meta))
            definitions.append(
                ToolDefinition(
                    name=tool.name,
                    description=tool.description,
                    input_schema=tool.input_schema,
                    source=self.name,
                    permission=permission,
                    prompt_template=_declared_prompt(tool.meta),
                )
            )
        logger.info(
            "Discovered %d tool(s) from MCP server '%s'", len(definitions), self.name
        )
        return definitions

    async def call_tool(self, name: str, arguments: dict[str, Any]) -> ToolResult:
        # Argument *values* are never logged — they may hold file or clipboard data.
        logger.info("Calling MCP tool '%s' (args: %s)", name, safe_keys(arguments))
        result = await self._session.call_tool(name, arguments)
        return ToolResult(
            content=result.text,
            structured=result.structured,
            is_error=result.is_error,
            metadata={"source": self.name},
        )


class MCPServerRegistry:
    """The set of MCP servers this backend connects to."""

    def __init__(self, servers: Iterable[MCPServerConfig] = ()) -> None:
        self._servers = list(servers)

    @classmethod
    def from_settings(cls, settings: Settings) -> MCPServerRegistry:
        """Build the registry from configuration.

        For v1 there is exactly one server: the bundled NEXUS Mac MCP server.
        """
        return cls(
            [
                MCPServerConfig(
                    name="nexus-mac",
                    command=settings.mcp_server_command,
                    args=tuple(settings.mcp_server_args),
                    cwd=str(BACKEND_ROOT),
                )
            ]
        )

    @property
    def servers(self) -> tuple[MCPServerConfig, ...]:
        return tuple(self._servers)

    async def probe(self) -> list[MCPServerStatus]:
        """Report the real state of each configured server.

        Every entry reflects an actual connection attempt — a server that is
        down is reported as disconnected, never as connected with zero tools.
        """
        statuses: list[MCPServerStatus] = []
        for config in self._servers:
            try:
                async with MCPClient(config).session() as session:
                    tools = await session.list_tools()
                statuses.append(
                    MCPServerStatus(
                        name=config.name, status="connected", tools=len(tools)
                    )
                )
            except MCPError as exc:
                logger.warning("MCP server '%s' is unreachable: %s", config.name, exc.detail)
                statuses.append(
                    MCPServerStatus(
                        name=config.name, status="disconnected", tools=0, reason=exc.message
                    )
                )
        return statuses

    async def open_sources(self, stack: AsyncExitStack) -> list[MCPToolSource]:
        """Open every configured server on ``stack`` and return its source.

        Must be called from the task that will also close ``stack``.
        """
        sources: list[MCPToolSource] = []
        for config in self._servers:
            session = await stack.enter_async_context(MCPClient(config).session())
            sources.append(MCPToolSource(session))
        return sources


class MCPSessionPool:
    """One long-lived session per configured server, for the backend's lifetime.

    Sessions used to be opened per agent run, which is fine for stateless
    tools but wrong once a server holds state: a development server started by
    one request would be killed when that request's session closed, and would
    be invisible to the next one. The pool is opened during application startup
    and closed during shutdown — the same task, as the stdio transport
    requires — so managed processes live as long as the backend does.
    """

    def __init__(self, registry: MCPServerRegistry) -> None:
        self._registry = registry
        self._stack: AsyncExitStack | None = None
        self._sources: list[MCPToolSource] = []

    @property
    def is_open(self) -> bool:
        return self._stack is not None

    @property
    def sources(self) -> list[MCPToolSource]:
        return list(self._sources)

    async def open(self) -> None:
        if self._stack is not None:  # pragma: no cover - defensive
            return
        stack = AsyncExitStack()
        try:
            self._sources = await self._registry.open_sources(stack)
        except MCPError:
            await stack.aclose()
            # Not fatal: callers fall back to a per-run session, so the backend
            # still starts when a server is temporarily unavailable.
            logger.warning("Could not open the MCP session pool; falling back per run")
            return
        self._stack = stack
        logger.info("MCP session pool open (%d server(s))", len(self._sources))

    async def close(self) -> None:
        if self._stack is None:
            return
        stack, self._stack = self._stack, None
        self._sources = []
        await stack.aclose()
        logger.info("MCP session pool closed")


@lru_cache(maxsize=1)
def get_mcp_registry() -> MCPServerRegistry:
    return MCPServerRegistry.from_settings(get_settings())


@lru_cache(maxsize=1)
def get_mcp_pool() -> MCPSessionPool:
    return MCPSessionPool(get_mcp_registry())
