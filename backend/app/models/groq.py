"""Groq provider — the default, used for fast tool selection."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from langchain_core.messages import AIMessage, BaseMessage

from app.core.errors import ConfigurationError, ModelError
from app.models.base import ModelProvider, ToolSpec, classify_provider_error


class GroqProvider(ModelProvider):
    name = "groq"

    def __init__(
        self,
        *,
        api_key: str | None,
        model: str | None,
        temperature: float = 0.0,
        timeout: float | None = None,
    ) -> None:
        if not api_key:
            raise ConfigurationError("Groq is not configured. Set GROQ_API_KEY in backend/.env.")
        if not model:
            raise ConfigurationError("Groq is not configured. Set GROQ_MODEL in backend/.env.")
        self._model = model
        self._api_key = api_key
        self._temperature = temperature
        self._timeout = timeout
        self._client: Any | None = None

    @property
    def model(self) -> str:
        return self._model

    def _get_client(self) -> Any:
        # Imported lazily so that merely importing the router does not require
        # the Groq stack to be importable.
        if self._client is None:
            from langchain_groq import ChatGroq

            self._client = ChatGroq(
                model=self._model,
                api_key=self._api_key,
                temperature=self._temperature,
                timeout=self._timeout,
            )
        return self._client

    async def ainvoke(
        self,
        messages: Sequence[BaseMessage],
        tools: Sequence[ToolSpec] = (),
        *,
        tool_choice: str | None = None,
    ) -> AIMessage:
        client = self._get_client()
        if tools:
            client = client.bind_tools(
                [tool.to_openai_tool() for tool in tools], tool_choice=tool_choice
            )
        try:
            response = await client.ainvoke(list(messages))
        except Exception as exc:  # noqa: BLE001 - vendor errors are opaque
            message, _category = classify_provider_error("Groq", "GROQ_API_KEY", exc)
            raise ModelError(message, detail=f"{type(exc).__name__}: {exc}") from exc
        if not isinstance(response, AIMessage):  # pragma: no cover - defensive
            raise ModelError(
                "The Groq model returned an unexpected response.",
                detail=f"got {type(response).__name__}",
            )
        return response
