"""Permission classification and policy.

Every tool carries a permission level. Tools the backend has never heard of are
treated as ``RESTRICTED`` — classification is opt-in, never inferred.
"""

from __future__ import annotations

from collections.abc import Collection, Mapping
from dataclasses import dataclass
from enum import StrEnum


class PermissionLevel(StrEnum):
    SAFE = "SAFE"
    """Read-only or otherwise harmless. Executed without asking."""

    CONFIRM = "CONFIRM"
    """Has an effect on the machine. Requires explicit user approval."""

    RESTRICTED = "RESTRICTED"
    """Destructive or security-sensitive. Never executed in v1."""


#: Deny-by-default: an unclassified tool is restricted until someone classifies it.
DEFAULT_PERMISSION_LEVEL = PermissionLevel.RESTRICTED

#: Baseline classification for the tools named in BACKEND_SPEC.md §16. A tool
#: may also declare its own level via MCP metadata, which wins over this table.
DEFAULT_PERMISSIONS: Mapping[str, PermissionLevel] = {
    # SAFE
    "system_info": PermissionLevel.SAFE,
    "battery_status": PermissionLevel.SAFE,
    "process_list": PermissionLevel.SAFE,
    "list_applications": PermissionLevel.SAFE,
    "search_files": PermissionLevel.SAFE,
    "read_file": PermissionLevel.SAFE,
    "read_clipboard": PermissionLevel.SAFE,
    "process_status": PermissionLevel.SAFE,
    # CONFIRM
    "write_file": PermissionLevel.CONFIRM,
    "create_directory": PermissionLevel.CONFIRM,
    "move_file": PermissionLevel.CONFIRM,
    "write_clipboard": PermissionLevel.CONFIRM,
    "open_application": PermissionLevel.CONFIRM,
    "close_application": PermissionLevel.CONFIRM,
    "send_notification": PermissionLevel.CONFIRM,
    "execute_command": PermissionLevel.CONFIRM,
    "create_event": PermissionLevel.CONFIRM,
    "update_event": PermissionLevel.CONFIRM,
    # RESTRICTED
    "delete_file": PermissionLevel.RESTRICTED,
    "delete_event": PermissionLevel.RESTRICTED,
    "mass_file_operations": PermissionLevel.RESTRICTED,
    "security_setting_changes": PermissionLevel.RESTRICTED,
}


def classify(tool_name: str, declared: str | None = None) -> PermissionLevel:
    """Resolve a tool's permission level.

    Precedence: the level the tool declares about itself, then the baseline
    table, then :data:`DEFAULT_PERMISSION_LEVEL`.
    """
    if declared:
        try:
            return PermissionLevel(declared.strip().upper())
        except ValueError:
            pass
    return DEFAULT_PERMISSIONS.get(tool_name, DEFAULT_PERMISSION_LEVEL)


@dataclass(frozen=True, slots=True)
class PermissionDecision:
    """Outcome of evaluating one tool call."""

    allowed: bool
    level: PermissionLevel
    requires_confirmation: bool = False
    reason: str = ""


class PermissionPolicy:
    """Decides whether a tool call may run.

    ``approved_tools`` are the tool names the user has explicitly approved for
    this request — the frontend collects the approval and resubmits.
    """

    def __init__(self, approved_tools: Collection[str] = ()) -> None:
        self._approved = frozenset(approved_tools)

    @property
    def approved_tools(self) -> frozenset[str]:
        return self._approved

    def evaluate(self, tool_name: str, level: PermissionLevel) -> PermissionDecision:
        if level is PermissionLevel.SAFE:
            return PermissionDecision(allowed=True, level=level)

        if level is PermissionLevel.CONFIRM:
            if tool_name in self._approved:
                return PermissionDecision(
                    allowed=True, level=level, reason="Approved by the user."
                )
            return PermissionDecision(
                allowed=False,
                level=level,
                requires_confirmation=True,
                reason=f"'{tool_name}' needs your approval before it can run.",
            )

        return PermissionDecision(
            allowed=False,
            level=level,
            reason=f"'{tool_name}' is restricted and cannot be run.",
        )
