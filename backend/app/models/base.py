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


#: Markers that identify a provider failure without depending on any one SDK's
#: exception classes. Checked against the exception's status code and text.
_RATE_LIMIT_MARKERS = ("rate_limit", "rate limit", "tokens per minute", "too large", "quota")
_TOOL_CALL_MARKERS = ("tool_use_failed", "tool call validation", "did not match schema")
_AUTH_MARKERS = ("invalid_api_key", "authentication", "unauthorized", "invalid api key")
_CONNECTIVITY_MARKERS = ("timeout", "timed out", "connection", "unreachable", "network")


def classify_provider_error(provider: str, env_var: str, exc: Exception) -> tuple[str, str]:
    """Turn an opaque vendor exception into (user_message, category).

    Every provider failure used to read "could not be reached", which sent
    people looking at their network when the real cause was a rate limit, a
    malformed tool call, or an unset key. The returned message is a fixed
    string per category: vendor text can carry an organisation id or account
    detail, so it stays in ``detail`` (logged) and never in the message
    (returned to the client).
    """
    status = getattr(exc, "status_code", None) or getattr(exc, "code", None)
    text = f"{type(exc).__name__}: {exc}".casefold()

    def mentions(markers: tuple[str, ...]) -> bool:
        return any(marker in text for marker in markers)

    if status in (401, 403) or mentions(_AUTH_MARKERS):
        return (
            f"{provider} rejected the API key. Check {env_var} in backend/.env.",
            "auth",
        )
    if status in (429, 413) or mentions(_RATE_LIMIT_MARKERS):
        return (
            f"{provider} is rate limiting this request — the conversation may also "
            f"be too long for the current plan. Wait a moment and try again.",
            "rate_limit",
        )
    if mentions(_TOOL_CALL_MARKERS):
        return (
            f"{provider} rejected the model's tool call as malformed. "
            f"Rephrasing the request usually clears it.",
            "tool_call",
        )
    if status == 404:
        return (f"{provider} does not offer the configured model.", "model_not_found")
    if mentions(_CONNECTIVITY_MARKERS):
        return (f"The {provider} model could not be reached.", "connectivity")
    return (f"The {provider} request failed.", "unknown")
