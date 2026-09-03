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
    nexus_api_url: str

    @classmethod
    def from_env(cls) -> EvalConfig:
        def _require(key: str) -> str:
            val = os.environ.get(key)
            if not val:
                raise RuntimeError(f"{key} is not set — copy evals/.env.example to evals/.env")
            return val

        return cls(
            langfuse_secret_key=_require("LANGFUSE_SECRET_KEY"),
            langfuse_public_key=_require("LANGFUSE_PUBLIC_KEY"),
            langfuse_host=os.environ.get("LANGFUSE_HOST", "https://cloud.langfuse.com"),
            nexus_api_url=os.environ.get("NEXUS_API_URL", "http://127.0.0.1:8000"),
        )
