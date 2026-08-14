"""Central tool registry.

The agent discovers and calls tools exclusively through this module. It has no
idea whether a tool is backed by MCP, an in-process function, or something else
added later — a source only has to satisfy :class:`ToolSource`.

    Agent -> ToolRegistry -> ToolSource (e.g. MCP) -> Tool
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable

from app.core.errors import ToolError
from app.models.base import ToolSpec
from app.tools.permissions import PermissionLevel


@dataclass(frozen=True, slots=True)
class ToolDefinition:
    """Everything the registry knows about one tool."""

    name: str
    description: str
    input_schema: dict[str, Any]
    source: str
    permission: PermissionLevel
    prompt_template: str | None = None
    """How to phrase an approval request, e.g. ``"Run {command} in {directory}"``.

    Declared by the tool's source. A tool's description is written for the
    model; the person deciding whether to allow an action deserves a sentence
    written for them.
    """

    def to_model_spec(self) -> ToolSpec:
        return ToolSpec(
            name=self.name,
            description=self.description,
            input_schema=self.input_schema,
        )

    def to_public_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "input_schema": self.input_schema,
            "source": self.source,
            "permission": str(self.permission),
        }


@dataclass(frozen=True, slots=True)
class ToolResult:
    """Normalised outcome of a tool execution."""

    content: str
    structured: Any = None
    is_error: bool = False
    metadata: dict[str, Any] = field(default_factory=dict)


@runtime_checkable
class ToolSource(Protocol):
    """A backend that can enumerate and execute tools."""

    @property
    def name(self) -> str: ...

    async def list_tools(self) -> Sequence[ToolDefinition]: ...

    async def call_tool(self, name: str, arguments: dict[str, Any]) -> ToolResult: ...


class ToolRegistry:
    """Aggregates tools from every registered source."""

    def __init__(self, sources: Iterable[ToolSource] = ()) -> None:
        self._sources: list[ToolSource] = list(sources)
        self._definitions: dict[str, ToolDefinition] = {}
        self._owners: dict[str, ToolSource] = {}

    def add_source(self, source: ToolSource) -> None:
        self._sources.append(source)

    async def refresh(self) -> None:
        """Re-discover tools from all sources.

        The first source to claim a name wins; later duplicates are ignored so
        one misbehaving server cannot hijack another's tool.
        """
        definitions: dict[str, ToolDefinition] = {}
        owners: dict[str, ToolSource] = {}
        for source in self._sources:
            for definition in await source.list_tools():
                if definition.name in definitions:
                    continue
                definitions[definition.name] = definition
                owners[definition.name] = source
        self._definitions = definitions
        self._owners = owners

    def list_tools(self) -> list[ToolDefinition]:
        return sorted(self._definitions.values(), key=lambda tool: tool.name)

    def get(self, name: str) -> ToolDefinition | None:
        return self._definitions.get(name)

    def require(self, name: str) -> ToolDefinition:
        definition = self._definitions.get(name)
        if definition is None:
            raise ToolError(f"Unknown tool '{name}'.")
        return definition

    def model_specs(
        self,
        exclude: Sequence[PermissionLevel] = (PermissionLevel.RESTRICTED,),
    ) -> list[ToolSpec]:
        """Tools offered to the model.

        Restricted tools are withheld by default: the model should not be able
        to propose an action the backend would always refuse.
        """
        excluded = set(exclude)
        return [
            tool.to_model_spec()
            for tool in self.list_tools()
            if tool.permission not in excluded
        ]

    async def call(self, name: str, arguments: dict[str, Any]) -> ToolResult:
        """Execute a tool. Permission checks happen *before* this is reached."""
        source = self._owners.get(name)
        if source is None:
            raise ToolError(f"Unknown tool '{name}'.")
        return await source.call_tool(name, arguments)
