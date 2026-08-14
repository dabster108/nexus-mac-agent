"""Centralised configuration for the NEXUS backend.

This is the *only* module allowed to read environment variables. Everything
else receives a :class:`Settings` instance (or calls :func:`get_settings`).
"""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from dotenv import load_dotenv

BACKEND_ROOT = Path(__file__).resolve().parents[2]
"""Absolute path to the ``backend/`` directory."""

SUPPORTED_PROVIDERS: tuple[str, ...] = ("groq", "mistral")

_DEFAULT_CORS_ORIGINS = "http://localhost:3000,http://127.0.0.1:3000"


def _get(name: str, default: str = "") -> str:
    return os.getenv(name, default).strip()


def _get_optional(name: str) -> str | None:
    value = _get(name)
    return value or None


def _get_int(name: str, default: int) -> int:
    raw = _get(name)
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError as exc:  # pragma: no cover - defensive
        raise ValueError(f"{name} must be an integer, got {raw!r}") from exc


def _get_float(name: str, default: float) -> float:
    raw = _get(name)
    if not raw:
        return default
    try:
        return float(raw)
    except ValueError as exc:  # pragma: no cover - defensive
        raise ValueError(f"{name} must be a number, got {raw!r}") from exc


def _get_csv(name: str, default: str = "") -> tuple[str, ...]:
    raw = _get(name, default)
    return tuple(item.strip() for item in raw.split(",") if item.strip())


def _cors_origins() -> tuple[str, ...]:
    """Origins allowed to call the API.

    ``FRONTEND_ORIGIN`` names the Next.js dev server; ``CORS_ORIGINS`` allows
    additional ones. A wildcard is never used — the agent can act on this Mac.
    """
    origins = list(_get_csv("CORS_ORIGINS", _DEFAULT_CORS_ORIGINS))
    frontend = _get("FRONTEND_ORIGIN")
    if frontend and frontend not in origins:
        origins.insert(0, frontend)
    return tuple(origin for origin in origins if origin != "*")


@dataclass(frozen=True, slots=True)
class Settings:
    """Immutable runtime configuration.

    Secrets live here and must never be serialised into an API response.
    """

    # --- credentials -------------------------------------------------
    groq_api_key: str | None
    mistral_api_key: str | None

    # --- models ------------------------------------------------------
    default_model_provider: str
    groq_model: str | None
    mistral_model: str | None
    model_temperature: float

    # --- server ------------------------------------------------------
    backend_host: str
    backend_port: int
    cors_origins: tuple[str, ...]

    # --- agent runtime ----------------------------------------------
    agent_max_iterations: int
    request_timeout_seconds: float
    permission_timeout_seconds: float

    # --- mission safety limits ---------------------------------------
    # Bound a multi-step mission the same way agent_max_iterations bounds a
    # single task: a runaway plan must fail loudly, never spin forever.
    mission_max_steps: int
    mission_max_retries_per_step: int
    mission_max_tool_calls: int
    mission_max_runtime_seconds: float

    # --- context budget ------------------------------------------------
    # What the planner is allowed to see of memory/workspace/machine state,
    # so a large memory store never floods the model's context window.
    context_max_memories: int
    context_max_workspace_facts: int
    context_max_chars: int

    # --- mcp ---------------------------------------------------------
    mcp_server_command: str
    mcp_server_args: tuple[str, ...]

    # --- observability ----------------------------------------------
    log_level: str

    service_name: str = "nexus-agent"

    def __post_init__(self) -> None:
        if self.default_model_provider not in SUPPORTED_PROVIDERS:
            raise ValueError(
                f"DEFAULT_MODEL_PROVIDER must be one of "
                f"{', '.join(SUPPORTED_PROVIDERS)}; got {self.default_model_provider!r}"
            )

    def model_for(self, provider: str) -> str | None:
        """Return the configured model identifier for ``provider``."""
        return {"groq": self.groq_model, "mistral": self.mistral_model}.get(provider)

    def api_key_for(self, provider: str) -> str | None:
        """Return the configured API key for ``provider``."""
        return {"groq": self.groq_api_key, "mistral": self.mistral_api_key}.get(provider)


def build_settings() -> Settings:
    """Read the environment (after loading ``.env``) into a ``Settings``."""
    load_dotenv(BACKEND_ROOT / ".env", override=False)
    return Settings(
        groq_api_key=_get_optional("GROQ_API_KEY"),
        mistral_api_key=_get_optional("MISTRAL_API_KEY"),
        default_model_provider=_get("DEFAULT_MODEL_PROVIDER", "groq").lower(),
        # Model identifiers are deliberately not defaulted: the operator picks a
        # model their account actually has access to.
        groq_model=_get_optional("GROQ_MODEL"),
        mistral_model=_get_optional("MISTRAL_MODEL"),
        model_temperature=_get_float("MODEL_TEMPERATURE", 0.0),
        backend_host=_get("BACKEND_HOST", "127.0.0.1"),
        backend_port=_get_int("BACKEND_PORT", 8000),
        cors_origins=_cors_origins(),
        agent_max_iterations=_get_int("AGENT_MAX_ITERATIONS", 6),
        request_timeout_seconds=_get_float("REQUEST_TIMEOUT_SECONDS", 60.0),
        permission_timeout_seconds=_get_float("PERMISSION_TIMEOUT_SECONDS", 300.0),
        mission_max_steps=_get_int("MISSION_MAX_STEPS", 30),
        mission_max_retries_per_step=_get_int("MISSION_MAX_RETRIES_PER_STEP", 2),
        mission_max_tool_calls=_get_int("MISSION_MAX_TOOL_CALLS", 50),
        mission_max_runtime_seconds=_get_float("MISSION_MAX_RUNTIME_SECONDS", 600.0),
        context_max_memories=_get_int("CONTEXT_MAX_MEMORIES", 10),
        context_max_workspace_facts=_get_int("CONTEXT_MAX_WORKSPACE_FACTS", 20),
        context_max_chars=_get_int("CONTEXT_MAX_CHARS", 4000),
        mcp_server_command=_get("MCP_SERVER_COMMAND", sys.executable),
        # The NEXUS Mac MCP server is a separate project installed into this
        # environment, so it runs under the same interpreter as the backend.
        mcp_server_args=_get_csv("MCP_SERVER_ARGS") or ("-m", "nexus_mac_mcp"),
        log_level=_get("LOG_LEVEL", "INFO").upper(),
    )


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Process-wide cached settings."""
    return build_settings()
