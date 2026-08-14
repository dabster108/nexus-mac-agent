"""Provider-neutral model interface.

The LangGraph agent talks to :class:`ModelProvider` only. It never imports a
vendor SDK, so swapping Groq for Mistral (or anything else later) does not
touch the graph.

LangChain message objects are used as the wire format because ``langchain-core``
is already part of the stack and gives us a well-defined tool-call shape.
Provider implementations translate to and from their own formats internally.
"""

from __future__ import annotations

import json
from abc import ABC, abstractmethod
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any

from langchain_core.messages import AIMessage, BaseMessage


@dataclass(frozen=True, slots=True)
class ToolSpec:
    """A tool as described *to a model*.

    Intentionally decoupled from how the tool is implemented or where it comes
    from — that lives in :mod:`app.tools.registry`.
    """

    name: str
    description: str
    input_schema: dict[str, Any] = field(default_factory=dict)

    def to_openai_tool(self) -> dict[str, Any]:
        """OpenAI-compatible function schema (Groq and Mistral both use it)."""
        parameters = self.input_schema or {"type": "object", "properties": {}}
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": parameters,
            },
        }


class ModelProvider(ABC):
    """A chat model that can optionally select tools."""

    #: Stable identifier, matching ``DEFAULT_MODEL_PROVIDER`` values.
    name: str

    @property
    @abstractmethod
    def model(self) -> str:
        """The concrete model identifier in use."""

    @abstractmethod
    async def ainvoke(
        self,
        messages: Sequence[BaseMessage],
        tools: Sequence[ToolSpec] = (),
        *,
        tool_choice: str | None = None,
    ) -> AIMessage:
        """Run one completion and return the assistant turn.

        ``tool_choice`` names a tool the model must call, rather than leaving
        selection to it. It exists for structured-output use (the mission
        planner asks for a single ``submit_plan`` tool this way) — ordinary
        tool-calling turns never pass it, so the default stays "pick freely or
        answer in text," unchanged from before this parameter existed.

        Implementations must raise :class:`app.core.errors.ModelError` (or a
        subclass) on failure rather than leaking vendor exceptions.
        """


def content_to_text(content: Any) -> str:
    """Flatten LangChain message content (str or content blocks) into text."""
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for block in content:
            if isinstance(block, str):
                parts.append(block)
            elif isinstance(block, dict):
                parts.append(str(block.get("text", "")))
            else:
                parts.append(str(getattr(block, "text", "")))
        return "".join(parts)
    return str(content)


def dumps_arguments(arguments: Any) -> str:
    """Serialise tool-call arguments to the JSON string vendors expect."""
    if isinstance(arguments, str):
        return arguments
    return json.dumps(arguments or {})


def loads_arguments(raw: Any) -> dict[str, Any]:
    """Parse vendor tool-call arguments into a dict, tolerating bad JSON."""
    if isinstance(raw, dict):
        return raw
    if not raw:
        return {}
    try:
        parsed = json.loads(raw)
    except (TypeError, ValueError):
        return {}
    return parsed if isinstance(parsed, dict) else {}
