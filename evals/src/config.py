"""Eval harness configuration — reads from evals/.env."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

_ENV_PATH = Path(__file__).resolve().parent.parent / ".env"
load_dotenv(_ENV_PATH)


@dataclass(frozen=True, slots=True)
class EvalConfig:
    langfuse_secret_key: str
    langfuse_public_key: str
    langfuse_host: str
    langfuse_environment: str
    nexus_api_url: str

    @classmethod
    def from_env(cls) -> EvalConfig:
        def _require(key: str) -> str:
            val = os.environ.get(key, "").strip()
            if not val or val.endswith("..."):
                raise RuntimeError(
                    f"{key} is not set — copy evals/.env.example to evals/.env "
                    "and paste keys from https://cloud.langfuse.com → Settings → API Keys"
                )
            return val

        return cls(
            langfuse_secret_key=_require("LANGFUSE_SECRET_KEY"),
            langfuse_public_key=_require("LANGFUSE_PUBLIC_KEY"),
            langfuse_host=os.environ.get("LANGFUSE_HOST", "https://cloud.langfuse.com").strip(),
            langfuse_environment=os.environ.get("LANGFUSE_ENVIRONMENT", "dev").strip() or "dev",
            nexus_api_url=os.environ.get("NEXUS_API_URL", "http://127.0.0.1:8000").strip(),
        )
