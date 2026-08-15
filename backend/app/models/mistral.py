"""Mistral provider — the secondary model backend.

There is no LangChain integration package for Mistral in this stack, so this
provider talks to the official SDK directly and translates to/from LangChain
messages at the boundary. Nothing outside this module knows about Mistral.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from typing import Any

from langchain_core.messages import (
    AIMessage,
    BaseMessage,
    HumanMessage,
    SystemMessage,
    ToolMessage,
)

from app.core.errors import ConfigurationError, ModelError
from app.models.base import (
    ModelProvider,
    ToolSpec,
    classify_provider_error,
    content_to_text as _content_to_text,
    dumps_arguments,
    loads_arguments,
)


def _forced_tool_choice(name: str) -> Any:
    """Mistral's shape for "you must call exactly this tool"."""
    from mistralai.client.models.functionname import FunctionName
    from mistralai.client.models.toolchoice import ToolChoice

    return ToolChoice(type="function", function=FunctionName(name=name))


def _to_mistral_messages(messages: Sequence[BaseMessage]) -> list[dict[str, Any]]:
    converted: list[dict[str, Any]] = []
    for message in messages:
        text = _content_to_text(message.content)
        if isinstance(message, SystemMessage):
            converted.append({"role": "system", "content": text})
        elif isinstance(message, HumanMessage):
            converted.append({"role": "user", "content": text})
        elif isinstance(message, ToolMessage):
            converted.append(
                {
                    "role": "tool",
                    "name": message.name,
                    "tool_call_id": message.tool_call_id,
                    "content": text,
                }
            )
        elif isinstance(message, AIMessage):
            entry: dict[str, Any] = {"role": "assistant", "content": text}
            if message.tool_calls:
                entry["tool_calls"] = [
                    {
                        "id": call.get("id") or uuid.uuid4().hex[:9],
                        "type": "function",
                        "function": {
                            "name": call["name"],
                            "arguments": dumps_arguments(call.get("args")),
                        },
                    }
                    for call in message.tool_calls
                ]
            converted.append(entry)
        else:  # pragma: no cover - defensive
            converted.append({"role": "user", "content": text})
    return converted


def _from_mistral_response(response: Any) -> AIMessage:
    choices = getattr(response, "choices", None) or []
    if not choices:
        raise ModelError(
            "The Mistral model returned an empty response.",
            detail="no choices in response",
        )
    message = choices[0].message
    tool_calls = []
    for call in getattr(message, "tool_calls", None) or []:
        function = getattr(call, "function", None)
        if function is None:
            continue
        tool_calls.append(
            {
                "name": function.name,
                "args": loads_arguments(getattr(function, "arguments", None)),
                "id": getattr(call, "id", None) or uuid.uuid4().hex[:9],
                "type": "tool_call",
            }
        )
    return AIMessage(
        content=_content_to_text(getattr(message, "content", "")),
        tool_calls=tool_calls,
    )


class MistralProvider(ModelProvider):
    name = "mistral"

    def __init__(
        self,
        *,
        api_key: str | None,
        model: str | None,
        temperature: float = 0.0,
        timeout: float | None = None,
    ) -> None:
        if not api_key:
            raise ConfigurationError(
                "Mistral is not configured. Set MISTRAL_API_KEY in backend/.env."
            )
        if not model:
            raise ConfigurationError(
                "Mistral is not configured. Set MISTRAL_MODEL in backend/.env."
            )
        self._model = model
        self._api_key = api_key
        self._temperature = temperature
        self._timeout = timeout
        self._client: Any | None = None

    @property
    def model(self) -> str:
        return self._model

    def _get_client(self) -> Any:
        if self._client is None:
            from mistralai.client import Mistral

            kwargs: dict[str, Any] = {"api_key": self._api_key}
            if self._timeout is not None:
                kwargs["timeout_ms"] = int(self._timeout * 1000)
            self._client = Mistral(**kwargs)
        return self._client

    async def ainvoke(
        self,
        messages: Sequence[BaseMessage],
        tools: Sequence[ToolSpec] = (),
        *,
        tool_choice: str | None = None,
    ) -> AIMessage:
        client = self._get_client()
        kwargs: dict[str, Any] = {
            "model": self._model,
            "messages": _to_mistral_messages(messages),
            "temperature": self._temperature,
        }
        if tools:
            kwargs["tools"] = [tool.to_openai_tool() for tool in tools]
            kwargs["tool_choice"] = (
                _forced_tool_choice(tool_choice) if tool_choice else "auto"
            )
        try:
            response = await client.chat.complete_async(**kwargs)
        except ModelError:
            raise
        except Exception as exc:  # noqa: BLE001 - vendor errors are opaque
            message, _category = classify_provider_error(
                "Mistral", "MISTRAL_API_KEY", exc
            )
            raise ModelError(message, detail=f"{type(exc).__name__}: {exc}") from exc
        return _from_mistral_response(response)
