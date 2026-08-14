"""MCP client layer.

Note: this package is named ``app.mcp``; the MCP SDK is the top-level ``mcp``
package. Absolute imports keep the two apart.
"""

from app.mcp.client import MCPClient, MCPServerConfig, MCPSession
from app.mcp.registry import MCPServerRegistry, MCPToolSource

__all__ = [
    "MCPClient",
    "MCPServerConfig",
    "MCPServerRegistry",
    "MCPSession",
    "MCPToolSource",
]
