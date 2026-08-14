"""check_local_service — local only, and only a verdict."""

from __future__ import annotations

import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from nexus_mac_mcp.tools.network import check_local_service


class _Handler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:  # noqa: N802 - http.server's interface
        if self.path == "/health":
            body = b'{"status":"ok"}'
            self.send_response(200)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        elif self.path == "/redirect":
            self.send_response(302)
            self.send_header("Location", "http://example.com/pwned")
            self.end_headers()
        else:
            self.send_response(404)
            self.end_headers()

    def log_message(self, *args: object) -> None:
        """Keep the test output quiet."""


@pytest.fixture
def local_server():
    server = HTTPServer(("127.0.0.1", 0), _Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{server.server_port}"
    server.shutdown()
    server.server_close()


# --- reachable -------------------------------------------------------------


def test_a_reachable_service(local_server: str) -> None:
    result = check_local_service(f"{local_server}/health")

    assert result["success"] is True
    assert result["reachable"] is True
    assert result["status_code"] == 200
    assert result["response_time_ms"] >= 0


def test_an_error_status_still_counts_as_reachable(local_server: str) -> None:
    result = check_local_service(f"{local_server}/missing")

    assert result["reachable"] is True
    assert result["status_code"] == 404


def test_the_response_body_is_not_returned(local_server: str) -> None:
    result = check_local_service(f"{local_server}/health")

    assert "body" not in result
    assert "status" not in str(result.get("content", ""))


def test_a_redirect_is_not_followed(local_server: str) -> None:
    """Otherwise a local service could use this as a proxy to anywhere."""
    result = check_local_service(f"{local_server}/redirect")

    assert result["reachable"] is True
    assert result["status_code"] == 302
    assert "example.com" not in str(result)


def test_an_unavailable_local_service(local_server: str) -> None:
    server, port = local_server.rsplit(":", 1)
    unused = f"{server}:{int(port) + 1}"

    result = check_local_service(f"{unused}/health")

    assert result["success"] is True
    assert result["reachable"] is False
    assert "No service answered" in result["error"]


# --- refused ---------------------------------------------------------------


@pytest.mark.parametrize(
    "url",
    [
        "http://example.com",
        "https://api.openai.com/v1/models",
        "http://192.168.1.1/admin",
        "http://10.0.0.1",
        "http://169.254.169.254/latest/meta-data/",  # cloud metadata
        "http://0.0.0.0:8000",
        "http://[::ffff:127.0.0.1]",
    ],
)
def test_non_local_urls_are_refused(url: str) -> None:
    result = check_local_service(url)

    assert result["reachable"] is False
    assert "local services" in result["error"]


@pytest.mark.parametrize(
    "url", ["file:///etc/passwd", "ftp://127.0.0.1", "gopher://127.0.0.1", "127.0.0.1:8000"]
)
def test_non_http_schemes_are_refused(url: str) -> None:
    result = check_local_service(url)

    assert result["reachable"] is False


def test_an_empty_url_is_refused() -> None:
    assert check_local_service("   ")["reachable"] is False


def test_an_over_long_url_is_refused() -> None:
    result = check_local_service("http://127.0.0.1/" + "a" * 400)

    assert "too long" in result["error"]


@pytest.mark.parametrize("host", ["127.0.0.1", "localhost"])
def test_loopback_names_are_accepted(host: str) -> None:
    """Accepted by the policy; whether anything answers is another matter."""
    result = check_local_service(f"http://{host}:9/health")

    assert "local services" not in result.get("error", "")


def test_credentials_in_a_url_are_refused() -> None:
    """`evil.example@127.0.0.1` reads as remote but resolves as local."""
    for url in (
        "http://evil.example@127.0.0.1",
        "http://user:pass@127.0.0.1:8000/health",
        "http://127.0.0.1@evil.example/",
    ):
        result = check_local_service(url)
        assert result["reachable"] is False
        assert "credentials" in result["error"]
