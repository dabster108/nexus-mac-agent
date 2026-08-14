"""Refusing to persist anything that looks like a credential.

Same philosophy as the filesystem layer's secret-file patterns
(:mod:`nexus_mac_mcp.core.filesystem`): a conservative baseline, not a
perfect scanner. Two independent signals, either one enough to refuse:

* **the field name** — a key called ``password``/``api_key``/``token`` is
  refused regardless of what the value looks like, because the *label* is
  the give-away.
* **the value's shape** — known credential prefixes (``sk-``, ``ghp_``,
  ``AKIA``, a JWT, ...) or a `.env`-style ``KEY=value`` line are refused
  regardless of what the field is called.

On a match, the write is refused outright. Nothing is redacted-and-saved:
partial credentials are still credentials.
"""

from __future__ import annotations

import re
from typing import Any

#: Substrings in a field name that mark it as holding a credential.
SECRET_KEY_MARKERS: tuple[str, ...] = (
    "password", "passwd", "secret", "token", "api_key", "apikey",
    "credential", "private_key", "privatekey", "access_key", "accesskey",
    "auth", "cookie", "session_id", "sessionid", "client_secret", "bearer",
    "ssh_key", "pgp", "passphrase",
)

#: Value shapes that are almost always a credential, wherever they appear.
_SECRET_VALUE_PATTERNS: tuple[re.Pattern[str], ...] = tuple(
    re.compile(pattern)
    for pattern in (
        r"\bsk-[A-Za-z0-9]{16,}\b",              # OpenAI-style
        r"\bgsk_[A-Za-z0-9]{16,}\b",              # Groq
        r"\bghp_[A-Za-z0-9]{20,}\b",               # GitHub PAT
        r"\bgithub_pat_[A-Za-z0-9_]{20,}\b",
        r"\bgho_[A-Za-z0-9]{20,}\b",
        r"\bAKIA[0-9A-Z]{12,}\b",                  # AWS access key id
        r"\bAIza[0-9A-Za-z\-_]{30,}\b",             # Google API key
        r"\bxox[baprs]-[A-Za-z0-9-]{10,}\b",       # Slack token
        r"-----BEGIN [A-Z ]*PRIVATE KEY-----",
        r"\beyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\b",  # JWT
        r"(?im)^\s*[A-Za-z_][A-Za-z0-9_]*(?:KEY|TOKEN|SECRET|PASSWORD)\s*=\s*\S+",  # .env line
        # Narrative phrasing: "my password is hunter2", "api key: sk-abc123".
        # Biased toward false positives on purpose — refusing an innocuous
        # sentence is recoverable; saving a real secret is not.
        r"(?i)\b(?:password|passwd|api[_ ]?key|secret|token|credential)s?\s*"
        r"(?:is|was|[:=])\s*\S{6,}",
    )
)

MAX_SCAN_DEPTH = 6


class SecretDetectedError(Exception):
    """The content refused to persist. The message is safe to show the agent."""


def _key_looks_secret(name: str) -> bool:
    lowered = name.casefold().replace("-", "_")
    return any(marker in lowered for marker in SECRET_KEY_MARKERS)


def _value_looks_secret(value: str) -> bool:
    return any(pattern.search(value) for pattern in _SECRET_VALUE_PATTERNS)


def find_secret(data: Any, *, path: str = "", depth: int = 0) -> str | None:
    """Walk a value (str, dict, list) looking for a credential.

    Returns a human-readable description of what was found, or ``None``.
    """
    if depth > MAX_SCAN_DEPTH:  # pragma: no cover - defensive, not reachable via JSON
        return None

    if isinstance(data, str):
        if _value_looks_secret(data):
            location = f" in '{path}'" if path else ""
            return f"a value that looks like a credential{location}"
        return None

    if isinstance(data, dict):
        for key, value in data.items():
            key_text = str(key)
            field = f"{path}.{key_text}" if path else key_text
            if _key_looks_secret(key_text) and isinstance(value, (str, int, float)) and str(value).strip():
                return f"a field named '{key_text}', which looks like a credential"
            found = find_secret(value, path=field, depth=depth + 1)
            if found:
                return found
        return None

    if isinstance(data, (list, tuple)):
        for index, item in enumerate(data):
            found = find_secret(item, path=f"{path}[{index}]", depth=depth + 1)
            if found:
                return found
        return None

    return None


def assert_no_secret(key: str, value: Any) -> None:
    """Raise :class:`SecretDetectedError` if ``key`` or ``value`` looks like a credential."""
    if _key_looks_secret(key):
        raise SecretDetectedError(
            f"'{key}' looks like a credential name, so this cannot be remembered."
        )
    found = find_secret(value)
    if found:
        raise SecretDetectedError(f"This looks like it contains {found}, so it cannot be remembered.")
