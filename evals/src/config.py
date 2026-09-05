"""Eval harness configuration — reads from evals/.env."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

_ENV_PATH = Path(__file__).resolve().parent.parent / ".env"
load_dotenv(_ENV_PATH)


def _env(key: str, default: str = "") -> str:
    return os.environ.get(key, default).strip()


def _looks_configured(value: str) -> bool:
    """True when a key is present and not still the .env.example placeholder."""
    return bool(value) and not value.endswith("...")


@dataclass(frozen=True, slots=True)
class EvalConfig:
    langfuse_secret_key: str | None
    langfuse_public_key: str | None
    langfuse_host: str
    langfuse_environment: str
    nexus_api_url: str
    dry_run: bool = False

    @property
    def langfuse_enabled(self) -> bool:
        """Whether this run should push observations to Langfuse."""
        return (
            not self.dry_run
            and _looks_configured(self.langfuse_secret_key or "")
            and _looks_configured(self.langfuse_public_key or "")
        )

    def require_langfuse(self) -> None:
        """Raise if Langfuse credentials are missing (non-dry-run runs)."""
        if self.langfuse_enabled:
            return
        if self.dry_run:
            return
        missing = [
            key
            for key, val in (
                ("LANGFUSE_SECRET_KEY", self.langfuse_secret_key),
                ("LANGFUSE_PUBLIC_KEY", self.langfuse_public_key),
            )
            if not _looks_configured(val or "")
        ]
        raise RuntimeError(
            "Langfuse is not configured ("
            + ", ".join(missing)
            + "). Copy evals/.env.example → evals/.env and paste keys from "
            "https://cloud.langfuse.com → Settings → API Keys, "
            "or run with --dry-run to score locally without Langfuse."
        )

    @classmethod
    def from_env(cls, *, dry_run: bool = False) -> EvalConfig:
        return cls(
            langfuse_secret_key=_env("LANGFUSE_SECRET_KEY") or None,
            langfuse_public_key=_env("LANGFUSE_PUBLIC_KEY") or None,
            langfuse_host=_env("LANGFUSE_HOST", "https://cloud.langfuse.com")
            or "https://cloud.langfuse.com",
            langfuse_environment=_env("LANGFUSE_ENVIRONMENT", "dev") or "dev",
            nexus_api_url=_env("NEXUS_API_URL", "http://127.0.0.1:8000")
            or "http://127.0.0.1:8000",
            dry_run=dry_run,
        )
