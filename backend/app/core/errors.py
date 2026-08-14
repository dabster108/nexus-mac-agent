"""Structured error types.

The backend never fails silently: every failure becomes a :class:`NexusError`
with a stable machine-readable code plus a clean, user-safe message. Technical
detail is carried separately so it can be logged without being returned to the
frontend.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Any


class ErrorCode(StrEnum):
    MODEL_ERROR = "MODEL_ERROR"
    TOOL_ERROR = "TOOL_ERROR"
    MCP_ERROR = "MCP_ERROR"
    PERMISSION_ERROR = "PERMISSION_ERROR"
    VALIDATION_ERROR = "VALIDATION_ERROR"
    TIMEOUT_ERROR = "TIMEOUT_ERROR"
    INTERNAL_ERROR = "INTERNAL_ERROR"


class NexusError(Exception):
    """Base class for all backend errors."""

    code: ErrorCode = ErrorCode.INTERNAL_ERROR
    http_status: int = 500

    def __init__(self, message: str, *, detail: str | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.detail = detail

    def to_payload(self) -> dict[str, Any]:
        """User-facing representation. Deliberately excludes ``detail``."""
        return {"code": str(self.code), "message": self.message}


class ModelError(NexusError):
    code = ErrorCode.MODEL_ERROR
    http_status = 502


class ToolError(NexusError):
    code = ErrorCode.TOOL_ERROR
    http_status = 500


class MCPError(NexusError):
    code = ErrorCode.MCP_ERROR
    http_status = 502


class PermissionError_(NexusError):
    """Named with a trailing underscore to avoid shadowing the builtin."""

    code = ErrorCode.PERMISSION_ERROR
    http_status = 403


class ValidationError(NexusError):
    code = ErrorCode.VALIDATION_ERROR
    http_status = 400


class TimeoutError_(NexusError):
    """Named with a trailing underscore to avoid shadowing the builtin."""

    code = ErrorCode.TIMEOUT_ERROR
    http_status = 504


class ConfigurationError(NexusError):
    """Misconfiguration (missing key, unknown provider, ...)."""

    code = ErrorCode.INTERNAL_ERROR
    http_status = 500
