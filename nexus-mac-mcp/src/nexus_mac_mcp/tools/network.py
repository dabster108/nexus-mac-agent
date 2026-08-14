"""SAFE tool: check whether a local development service is responding.

This is not a web client and must not become one. Only loopback addresses are
reachable, redirects are never followed (otherwise a local service could bounce
this at any host it liked, turning the tool into a request proxy), and the
response body is never returned — only whether the service answered, with what
status, and how quickly.
"""

from __future__ import annotations

import time
import urllib.error
import urllib.request
from typing import Any
from urllib.parse import urlparse

from nexus_mac_mcp.core.commands import LOCAL_HOSTS

ALLOWED_SCHEMES = frozenset({"http", "https"})
DEFAULT_TIMEOUT_SECONDS = 5.0
MAX_URL_LENGTH = 300


class _NoRedirects(urllib.request.HTTPRedirectHandler):
    """Turns a redirect into a plain response instead of following it."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):  # type: ignore[no-untyped-def]
        return None


_opener = urllib.request.build_opener(_NoRedirects)


def _failure(error: str) -> dict[str, Any]:
    return {"success": False, "reachable": False, "error": error}


def check_local_service(
    url: str, timeout: float = DEFAULT_TIMEOUT_SECONDS
) -> dict[str, Any]:
    """Ask a service on this machine whether it is up."""
    text = (url or "").strip()
    if not text:
        return _failure("A URL is required.")
    if len(text) > MAX_URL_LENGTH:
        return _failure("That URL is too long.")

    try:
        parsed = urlparse(text)
    except ValueError:
        return _failure("That URL could not be parsed.")

    if parsed.scheme not in ALLOWED_SCHEMES:
        return _failure("Only http and https URLs can be checked.")
    if "@" in parsed.netloc:
        # `http://evil.example@127.0.0.1` parses as userinfo + host, which reads
        # as remote but resolves as local. Rather than reason about which half
        # wins in which parser, refuse credentials in the URL at all.
        return _failure("URLs with credentials in them cannot be checked.")
    if parsed.hostname is None or parsed.hostname.lower() not in LOCAL_HOSTS:
        return _failure(
            "Only local services can be checked (127.0.0.1, localhost or ::1)."
        )

    started = time.perf_counter()
    request = urllib.request.Request(text, method="GET")
    try:
        with _opener.open(request, timeout=timeout) as response:
            status = response.status
            response.read(0)  # the body is deliberately not returned
    except urllib.error.HTTPError as exc:
        # A 404 or 500 still means something answered.
        status = exc.code
    except (urllib.error.URLError, OSError, ValueError) as exc:
        reason = getattr(exc, "reason", exc)
        return {
            "success": True,
            "reachable": False,
            "url": text,
            "error": f"No service answered: {reason}",
            "response_time_ms": round((time.perf_counter() - started) * 1000, 1),
        }

    return {
        "success": True,
        "reachable": True,
        "url": text,
        "status_code": status,
        "response_time_ms": round((time.perf_counter() - started) * 1000, 1),
    }
