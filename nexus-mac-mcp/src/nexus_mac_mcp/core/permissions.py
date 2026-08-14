"""Permission *declaration*.

This server does not enforce permissions and must not try to. It declares what
each tool is, in metadata the NEXUS backend reads at discovery time; the
backend's permission policy and approval broker remain the only authority over
whether a call actually runs.

The metadata shape is the one the backend already looks for::

    {"nexus": {"permission": "CONFIRM"}}
"""

from __future__ import annotations

from enum import StrEnum
from typing import Any

#: Namespace the NEXUS backend reads tool metadata from.
META_NAMESPACE = "nexus"


class Permission(StrEnum):
    SAFE = "SAFE"
    """Read-only. Nothing about the machine changes."""

    CONFIRM = "CONFIRM"
    """Has a visible effect. The backend asks the user first."""

    RESTRICTED = "RESTRICTED"
    """Destructive or security-sensitive. Nothing here declares this yet."""


def meta(permission: Permission, prompt: str | None = None) -> dict[str, Any]:
    """Build the ``_meta`` payload announcing a tool's classification.

    ``prompt`` is an optional template the backend renders with the call's
    arguments to phrase the approval request — e.g. ``"Run {command} in
    {working_directory}"``. Without one the backend falls back to the tool's
    description, which is written for the model rather than for someone
    deciding whether to allow something.
    """
    payload: dict[str, Any] = {"permission": str(permission)}
    if prompt:
        payload["prompt"] = prompt
    return {META_NAMESPACE: payload}


SAFE = meta(Permission.SAFE)
CONFIRM = meta(Permission.CONFIRM)
