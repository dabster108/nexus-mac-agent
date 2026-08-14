"""MCP client foundation.

This module owns the transport and speaks only in MCP terms. It has no
knowledge of the agent, the tool registry, or permissions — that mapping lives
in :mod:`app.mcp.registry`.

A connection is scoped to an ``async with`` block. The stdio transport spawns
and supervises a child process inside an anyio task group, so the session must
be opened and closed from the same task; the agent runner does exactly that,
holding one session for the lifetime of a task run.
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator, Mapping, Sequence
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from typing import Any

from app.core.errors import MCPError
from app.core.logging import get_logger

logger = get_logger(__name__)


@dataclass(frozen=True, slots=True)
class MCPServerConfig:
    """How to reach one MCP server (stdio only for now)."""

    name: str
    command: str
    args: tuple[str, ...] = ()
    env: Mapping[str, str] | None = None
    cwd: str | None = None


@dataclass(frozen=True, slots=True)
class MCPToolInfo:
    """A tool as advertised by an MCP server."""

    name: str
    description: str
    input_schema: dict[str, Any]
    meta: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class MCPCallResult:
    """Raw outcome of an MCP ``tools/call``."""

    text: str
    structured: Any = None
    is_error: bool = False


def _blocks_to_text(content: Sequence[Any]) -> str:
    parts: list[str] = []
    for block in content:
        text = getattr(block, "text", None)
        if text is not None:
            parts.append(str(text))
            continue
        data = getattr(block, "data", None)
        if data is not None:
            parts.append(f"[{getattr(block, 'type', 'binary')} content]")
            continue
        parts.append(str(block))
    return "\n".join(part for part in parts if part)


class MCPSession:
    """An open connection to a single MCP server."""

    def __init__(self, server_name: str, client: Any) -> None:
        self._server_name = server_name
        self._client = client

    @property
    def server_name(self) -> str:
        return self._server_name

    async def list_tools(self) -> list[MCPToolInfo]:
        try:
            result = await self._client.list_tools()
        except Exception as exc:  # noqa: BLE001 - protocol/transport errors
            raise MCPError(
                f"Could not list tools from MCP server '{self._server_name}'.",
                detail=f"{type(exc).__name__}: {exc}",
            ) from exc

        tools: list[MCPToolInfo] = []
        for tool in result.tools:
            meta = getattr(tool, "meta", None) or {}
            tools.append(
                MCPToolInfo(
                    name=tool.name,
                    description=tool.description or "",
                    input_schema=dict(tool.input_schema or {}),
                    meta=dict(meta) if isinstance(meta, Mapping) else {},
                )
            )
        return tools

    async def call_tool(self, name: str, arguments: dict[str, Any]) -> MCPCallResult:
        try:
            result = await self._client.call_tool(name, arguments)
        except Exception as exc:  # noqa: BLE001 - protocol/transport errors
            raise MCPError(
                f"MCP server '{self._server_name}' failed while running '{name}'.",
                detail=f"{type(exc).__name__}: {exc}",
            ) from exc

        text = _blocks_to_text(result.content or [])
        structured = result.structured_content
        if not text and structured is not None:
            text = json.dumps(structured, default=str)
        return MCPCallResult(text=text, structured=structured, is_error=bool(result.is_error))


class MCPClient:
    """Opens sessions against one configured MCP server."""

    def __init__(self, config: MCPServerConfig) -> None:
        self._config = config

    @property
    def config(self) -> MCPServerConfig:
        return self._config

    @asynccontextmanager
    async def session(self) -> AsyncIterator[MCPSession]:
        """Connect, yield a session, then shut the server down."""
        # Imported here so the rest of the backend stays importable even if the
        # MCP SDK is unavailable.
        from mcp import Client, StdioServerParameters, stdio_client

        params = StdioServerParameters(
            command=self._config.command,
            args=list(self._config.args),
            env=dict(self._config.env) if self._config.env else None,
            cwd=self._config.cwd,
        )
        logger.info("Connecting to MCP server '%s'", self._config.name)
        try:
            async with Client(stdio_client(params)) as client:
                yield MCPSession(self._config.name, client)
        except MCPError:
            raise
        except Exception as exc:  # noqa: BLE001 - transport/startup failures
            raise MCPError(
                f"Could not connect to MCP server '{self._config.name}'.",
                detail=f"{type(exc).__name__}: {exc}",
            ) from exc
        finally:
            logger.info("Closed MCP server '%s'", self._config.name)
