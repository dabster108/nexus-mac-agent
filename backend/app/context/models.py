"""The structured context assembled before planning.

Section 14's rule, made concrete: "do not construct giant prompt strings
manually throughout the codebase." Every piece of context — memory, workspace,
machine, mission — is a typed object, and :meth:`PlanningContext.to_prompt_block`
is the *one* place any of it becomes a string. Nothing else in the codebase
formats context into text.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True, slots=True)
class ContextBudget:
    """§15: never dump the whole memory store into a prompt."""

    max_memories: int
    max_workspace_facts: int
    max_chars: int


@dataclass(frozen=True, slots=True)
class RetrievedMemory:
    """One memory, as surfaced to the planner — never authoritative on its own."""

    id: str
    type: str
    key: str
    value: dict[str, Any]
    confidence: float
    stale: bool = False
    conflict: str | None = None

    def to_line(self) -> str:
        marker = ""
        if self.stale:
            marker = " [STALE — the remembered path no longer exists]"
        elif self.conflict:
            marker = f" [CONFLICT — {self.conflict}]"
        return f"- {self.type} {self.key}: {self.value}{marker}"


@dataclass(frozen=True, slots=True)
class WorkspaceContext:
    """What the current filesystem/Git state actually says about a project.

    Always gathered fresh from the existing SAFE tools (detect_workspace,
    git_status) — never constructed from memory alone, which is what makes it
    outrank memory in the precedence order.
    """

    path: str
    verified: bool
    project_types: tuple[str, ...] = ()
    is_git_repository: bool = False
    git_branch: str | None = None
    git_clean: bool | None = None

    def to_line(self) -> str:
        if not self.verified:
            return f"- {self.path}: could not be verified (no longer exists?)"
        bits = [", ".join(self.project_types) or "unknown project type"]
        if self.is_git_repository:
            state = "clean" if self.git_clean else "has uncommitted changes"
            bits.append(f"git branch '{self.git_branch}' ({state})")
        return f"- {self.path}: {'; '.join(bits)}"


@dataclass(frozen=True, slots=True)
class MachineContext:
    """A snapshot of the machine, gathered once per collection — never polled."""

    platform: str
    architecture: str
    cpu_count: int
    battery_percentage: int | None = None
    charging: bool | None = None

    def to_line(self) -> str:
        battery = ""
        if self.battery_percentage is not None:
            state = "charging" if self.charging else "on battery"
            battery = f", battery {self.battery_percentage}% ({state})"
        return f"- {self.platform}/{self.architecture}, {self.cpu_count} CPUs{battery}"


@dataclass(frozen=True, slots=True)
class PlanningContext:
    """Everything context-collection gathered for one objective."""

    objective: str
    memories: tuple[RetrievedMemory, ...] = ()
    workspaces: tuple[WorkspaceContext, ...] = ()
    machine: MachineContext | None = None
    truncated: bool = False

    def to_prompt_block(self, max_chars: int) -> str:
        """The one place context becomes a prompt string.

        Precedence is stated explicitly, not left to the model to infer: a
        tool's current result always outranks anything remembered here.
        """
        if not self.memories and not self.workspaces and not self.machine:
            return ""

        lines: list[str] = ["Context gathered before planning:"]
        if self.memories:
            lines.append("Remembered facts (verify before trusting; a stale or")
            lines.append("conflicting one is marked — prefer a fresh tool result):")
            lines.extend(memory.to_line() for memory in self.memories)
        if self.workspaces:
            lines.append("Current workspace state (already verified just now):")
            lines.extend(workspace.to_line() for workspace in self.workspaces)
        if self.machine:
            lines.append("This machine:")
            lines.append(self.machine.to_line())
        lines.append(
            "Precedence: a tool's current result always outranks anything above. "
            "Memory is a hint for where to look, not a substitute for checking."
        )

        text = "\n".join(lines)
        if len(text) > max_chars:
            text = text[: max_chars - 1].rstrip() + "…"
        return text

    def summary(self) -> dict[str, Any]:
        """A concise, non-sensitive summary for the context_collected event."""
        return {
            "memories": len(self.memories),
            "workspaces": len(self.workspaces),
            "machine": self.machine is not None,
            "truncated": self.truncated,
        }
