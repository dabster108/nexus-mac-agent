"""Shared foundations: platform guards and permission metadata."""

from nexus_mac_mcp.core.permissions import CONFIRM, SAFE, META_NAMESPACE, Permission, meta
from nexus_mac_mcp.core.platform import (
    MACOS_REQUIRED_MESSAGE,
    CommandError,
    is_macos,
    require_macos,
    run,
)

__all__ = [
    "CONFIRM",
    "MACOS_REQUIRED_MESSAGE",
    "META_NAMESPACE",
    "SAFE",
    "CommandError",
    "Permission",
    "is_macos",
    "meta",
    "require_macos",
    "run",
]
