"""Structured logging for the backend.

Every task is traceable through the ``task_id`` extra. Secrets are never
logged: tool arguments are reduced to their key names via :func:`safe_keys`.
"""

from __future__ import annotations

import logging
import sys
from collections.abc import Mapping
from typing import Any

_CONFIGURED = False

_FORMAT = "%(asctime)s %(levelname)-8s [%(name)s]%(task_suffix)s %(message)s"


class _TaskFilter(logging.Filter):
    """Ensure ``task_suffix`` always exists so the formatter never blows up."""

    def filter(self, record: logging.LogRecord) -> bool:
        task_id = getattr(record, "task_id", None)
        record.task_suffix = f" [{task_id}]" if task_id else ""
        return True


def configure_logging(level: str = "INFO") -> None:
    """Install the root handler. Safe to call more than once."""
    global _CONFIGURED
    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(logging.Formatter(_FORMAT))
    handler.addFilter(_TaskFilter())

    root = logging.getLogger()
    if _CONFIGURED:
        root.setLevel(level)
        return
    root.handlers = [handler]
    root.setLevel(level)
    # LangChain/httpx are chatty at DEBUG; keep them at WARNING.
    for noisy in ("httpx", "httpcore", "langchain_core", "urllib3"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
    _CONFIGURED = True


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name)


def safe_keys(arguments: Mapping[str, Any] | None) -> list[str]:
    """Return only the *names* of tool arguments.

    Values may contain file contents, clipboard data or credentials, so they
    are never written to the log.
    """
    if not arguments:
        return []
    return sorted(str(key) for key in arguments)
