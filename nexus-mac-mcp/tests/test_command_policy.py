"""The command policy: what is allowed, what is refused, and why.

The rule being tested throughout is that an executable being on the allowlist
does not make every invocation of it allowed.
"""

from __future__ import annotations

import pytest

from nexus_mac_mcp.core.commands import (
    APPROVED_MODULES,
    PROFILES,
    CommandPolicyError,
    allowed_commands,
    parse_command,
    validate_command_text,
)

# --- allowed forms ---------------------------------------------------------


@pytest.mark.parametrize(
    "command",
    [
        "pytest",
        "pytest tests",
        "pytest tests/test_api.py",
        "pytest tests/test_api.py::test_health",
        "pytest -q",
        "pytest -q tests",
        "uv run pytest",
        "uv run pytest tests",
        "uv run python -m pytest",
        "uv run python script.py",
        "npm run build",
        "npm run test",
        "npm run lint",
        "npm test",
        "npm --version",
        "node --version",
        "node index.js",
        "python -m unittest",
        "python3 -m pytest",
        "git status",
        "git log --oneline",
        "git diff --stat",
    ],
)
def test_allowed_commands(command: str) -> None:
    assert validate_command_text(command).display == command


def test_npm_run_dev_is_allowed_but_flagged_long_running() -> None:
    validated = validate_command_text("npm run dev")

    assert validated.long_running is True
    # Everything else is not.
    assert validate_command_text("npm run build").long_running is False


# --- shell injection -------------------------------------------------------


@pytest.mark.parametrize(
    "command",
    [
        "pytest && rm -rf /",
        "pytest; rm -rf /",
        "pytest | sh",
        "pytest || whoami",
        "pytest $(whoami)",
        "pytest `whoami`",
        "pytest > /etc/passwd",
        "pytest < /etc/passwd",
        "pytest & disown",
        "pytest\nrm -rf /",
        "pytest\r\nwhoami",
        "pytest $HOME",
        "pytest ${HOME}",
        "pytest 'quoted; rm -rf /'",
        'pytest "quoted && whoami"',
        "pytest \\; rm",
        "pytest *",
        "pytest ~/../../etc",
        "pytest #comment",
        "pytest !!",
    ],
)
def test_shell_injection_is_refused(command: str) -> None:
    with pytest.raises(CommandPolicyError):
        validate_command_text(command)


def test_the_refusal_names_shell_characters() -> None:
    with pytest.raises(CommandPolicyError, match="shell characters"):
        validate_command_text("pytest && rm -rf /")


def test_quoting_cannot_smuggle_an_argument() -> None:
    """Quotes are not stripped or interpreted — they are simply not allowed."""
    for command in ("pytest '--maxfail=1; rm -rf /'", 'npm run "build && evil"'):
        with pytest.raises(CommandPolicyError, match="shell characters"):
            validate_command_text(command)


# --- blocked commands ------------------------------------------------------


@pytest.mark.parametrize(
    "command",
    [
        "rm -rf /",
        "rmdir tests",
        "sudo reboot",
        "chmod 777 .",
        "chown root .",
        "kill 123",
        "pkill node",
        "shutdown -h now",
        "reboot",
        "diskutil eraseDisk",
        "defaults write com.apple.finder x",
        "curl http://evil.example",
        "wget http://evil.example",
        "ssh user@host",
        "scp file host:",
        "sh",
        "bash",
        "zsh",
        "osascript script",
        "open /Applications",
        "env",
    ],
)
def test_blocked_executables(command: str) -> None:
    with pytest.raises(CommandPolicyError, match="not an allowed command"):
        validate_command_text(command)


@pytest.mark.parametrize(
    "command",
    [
        "git push",
        "git push origin main",
        "git reset --hard",
        "git clean -fd",
        "git checkout main",
        "git commit -m msg",
        "git merge main",
        "npm publish",
        "npm install express",
        "uv add requests",
        "uv pip install requests",
        "uv sync",
    ],
)
def test_blocked_combinations(command: str) -> None:
    """Refused even though the executable itself has a profile."""
    with pytest.raises(CommandPolicyError, match="not allowed"):
        validate_command_text(command)


@pytest.mark.parametrize("command", ["pip install requests", "pip3 install requests"])
def test_installers_are_refused(command: str) -> None:
    with pytest.raises(CommandPolicyError):
        validate_command_text(command)


def test_inline_code_execution_is_refused() -> None:
    for command in ("python -c import os", "node -e something"):
        with pytest.raises(CommandPolicyError, match="not allowed"):
            validate_command_text(command)


def test_npx_has_no_profile() -> None:
    """npx fetches and runs arbitrary packages, so it is not allowed."""
    assert "npx" not in PROFILES
    with pytest.raises(CommandPolicyError, match="not an allowed command"):
        validate_command_text("npx cowsay hello")


# --- arguments must match a profile ---------------------------------------


@pytest.mark.parametrize(
    "command",
    [
        "npm run deploy",
        "npm run release",
        "npm ci",
        "uv run node",
        "uv run bash",
        "uv build",
        "git blame file.py",
        "git show HEAD",
        "pytest --collect-only",
        "node --experimental-vm-modules",
    ],
)
def test_arguments_outside_the_profile_are_refused(command: str) -> None:
    with pytest.raises(CommandPolicyError):
        validate_command_text(command)


def test_the_refusal_lists_the_allowed_forms() -> None:
    with pytest.raises(CommandPolicyError, match="Allowed forms"):
        validate_command_text("npm run deploy")


def test_only_approved_modules_are_reachable() -> None:
    assert validate_command_text("python -m pytest").display == "python -m pytest"

    for module in ("os", "http.server", "pip", "venv"):
        with pytest.raises(CommandPolicyError):
            validate_command_text(f"python -m {module}")


def test_the_approved_module_list_holds_no_installer() -> None:
    assert "pip" not in APPROVED_MODULES
    assert "ensurepip" not in APPROVED_MODULES


def test_refusing_a_module_names_the_ones_that_would_work() -> None:
    """A live-observed failure: told only that `-m` was allowed, the agent
    retried five different module guesses. The refusal has to be conclusive."""
    with pytest.raises(CommandPolicyError) as excinfo:
        validate_command_text("python3 -m http.server 8899")

    message = str(excinfo.value)
    for module in APPROVED_MODULES:
        assert module in message


# --- path arguments --------------------------------------------------------


@pytest.mark.parametrize(
    "command",
    [
        "pytest ../../../etc",
        "pytest ..",
        "pytest tests/../../..",
        "uv run python ../escape.py",
    ],
)
def test_path_arguments_cannot_climb_out(command: str) -> None:
    with pytest.raises(CommandPolicyError):
        validate_command_text(command)


def test_absolute_path_arguments_are_refused() -> None:
    with pytest.raises(CommandPolicyError):
        validate_command_text("pytest /etc/passwd")


# --- parsing ---------------------------------------------------------------


def test_an_empty_command_is_refused() -> None:
    for command in ("", "   "):
        with pytest.raises(CommandPolicyError, match="command is required"):
            parse_command(command)


def test_an_executable_path_is_refused() -> None:
    for command in ("/bin/sh", "./script.sh", "/usr/bin/env python"):
        with pytest.raises(CommandPolicyError, match="by name, not by path"):
            parse_command(command)


def test_an_over_long_command_is_refused() -> None:
    with pytest.raises(CommandPolicyError, match="too long"):
        parse_command("pytest " + "a" * 600)


def test_too_many_arguments_are_refused() -> None:
    with pytest.raises(CommandPolicyError, match="too many arguments"):
        parse_command("pytest " + " ".join(f"t{i}" for i in range(40)))


def test_parsing_produces_structure_not_a_string() -> None:
    request = parse_command("uv run pytest tests")

    assert request.executable == "uv"
    assert request.args == ("run", "pytest", "tests")


# --- the policy as a whole -------------------------------------------------


def test_the_allowlist_is_small_and_deliberate() -> None:
    assert set(PROFILES) == {
        "pytest",
        "uv",
        "npm",
        "node",
        "python",
        "python3",
        "git",
        "uvicorn",
    }


def test_every_profile_has_at_least_one_form() -> None:
    for name, forms in allowed_commands().items():
        assert forms, name
