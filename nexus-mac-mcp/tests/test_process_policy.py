"""Which commands may become background processes.

The point of these tests is that the background layer *narrows* the existing
command policy rather than adding a second, looser one.
"""

from __future__ import annotations

import pytest

from nexus_mac_mcp.core.commands import (
    LOCAL_HOSTS,
    MAX_PORT,
    MIN_PORT,
    CommandPolicyError,
    validate_command_text,
)
from nexus_mac_mcp.core.process_policy import (
    background_commands,
    validate_process_command,
)


# --- supported background commands ----------------------------------------


@pytest.mark.parametrize(
    "command",
    [
        "npm run dev",
        "npm start",
        "npm run start",
        "uvicorn app.main:app --reload",
        "uvicorn app.main:app",
        "uvicorn app.main:app --reload --host 127.0.0.1 --port 8000",
        "uvicorn backend.main:application --port 3001",
        # uvicorn usually lives in the project's environment, not on PATH.
        "uv run uvicorn app.main:app --reload",
        "uv run uvicorn app.main:app --reload --port 8123",
    ],
)
def test_supported_background_commands(command: str) -> None:
    assert validate_process_command(command).display == command


def test_the_supported_set_is_small() -> None:
    assert background_commands() == [
        "npm run dev",
        "npm start",
        "npm run start",
        "uvicorn",
        "uv run uvicorn",
    ]


# --- the command policy is reused, not duplicated --------------------------


@pytest.mark.parametrize(
    "command",
    [
        "rm -rf /",
        "sudo reboot",
        "npm run dev && rm -rf /",
        "npm run dev; whoami",
        "npm run dev | sh",
        "curl http://evil.example",
        "npx serve",
        "git push",
    ],
)
def test_the_ordinary_command_policy_still_applies(command: str) -> None:
    """Anything the command policy refuses is refused here too."""
    with pytest.raises(CommandPolicyError):
        validate_command_text(command)
    with pytest.raises(CommandPolicyError):
        validate_process_command(command)


@pytest.mark.parametrize(
    "command", ["pytest", "npm run build", "npm test", "uv run pytest", "git status"]
)
def test_short_lived_commands_are_not_background_eligible(command: str) -> None:
    """Allowed to run, but not allowed to be left running."""
    assert validate_command_text(command)  # fine for run_command

    with pytest.raises(CommandPolicyError, match="run_command"):
        validate_process_command(command)


# --- network constraints ---------------------------------------------------


@pytest.mark.parametrize(
    "command",
    [
        "uvicorn app.main:app --host 0.0.0.0",
        "uvicorn app.main:app --reload --host 0.0.0.0",
        "uvicorn app.main:app --host 192.168.1.50",
        "uvicorn app.main:app --host 10.0.0.1",
        "uvicorn app.main:app --host example.com",
        "uvicorn app.main:app --host ::",
    ],
)
def test_public_binding_is_refused(command: str) -> None:
    """A development server NEXUS starts must not be reachable from the network."""
    with pytest.raises(CommandPolicyError):
        validate_process_command(command)


@pytest.mark.parametrize("host", sorted(LOCAL_HOSTS))
def test_loopback_binding_is_allowed(host: str) -> None:
    validated = validate_process_command(f"uvicorn app.main:app --host {host}")

    assert validated.host == host


@pytest.mark.parametrize("port", ["80", "443", "22", "0", "1023", "65536", "99999", "abc", "-1"])
def test_disallowed_ports_are_refused(port: str) -> None:
    with pytest.raises(CommandPolicyError):
        validate_process_command(f"uvicorn app.main:app --port {port}")


@pytest.mark.parametrize("port", [MIN_PORT, 3000, 8000, MAX_PORT])
def test_allowed_ports(port: int) -> None:
    assert validate_process_command(f"uvicorn app.main:app --port {port}").port == port


def test_the_port_is_recorded() -> None:
    validated = validate_process_command("uvicorn app.main:app --reload --port 9001")

    assert validated.port == 9001
    assert validated.host == "127.0.0.1"


def test_uvicorn_defaults_to_its_usual_port_on_loopback() -> None:
    validated = validate_process_command("uvicorn app.main:app --reload")

    assert validated.port == 8000
    assert validated.host == "127.0.0.1"


def test_npm_has_no_assumed_port() -> None:
    """The port lives in project config, so guessing it would be wrong."""
    assert validate_process_command("npm run dev").port is None


# --- arbitrary flags -------------------------------------------------------


@pytest.mark.parametrize(
    "command",
    [
        "uvicorn app.main:app --workers 4",
        "uvicorn app.main:app --ssl-keyfile key.pem",
        "uvicorn app.main:app --root-path /admin",
        "uvicorn app.main:app --log-config config.json",
        "uvicorn app.main:app --factory",
        "uvicorn app.main:app --reload-dir /etc",
    ],
)
def test_arbitrary_uvicorn_flags_are_refused(command: str) -> None:
    with pytest.raises(CommandPolicyError):
        validate_process_command(command)


@pytest.mark.parametrize(
    "target",
    ["/etc/passwd", "../escape:app", "app.main", "app.main:", ":app", "app/main:app"],
)
def test_only_a_real_asgi_target_is_accepted(target: str) -> None:
    with pytest.raises(CommandPolicyError):
        validate_process_command(f"uvicorn {target} --reload")


def test_an_option_without_a_value_is_refused() -> None:
    for command in ("uvicorn app.main:app --port", "uvicorn app.main:app --host"):
        with pytest.raises(CommandPolicyError):
            validate_process_command(command)
