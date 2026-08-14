"""SAFE system tools."""

from __future__ import annotations

from conftest import macos_only

from nexus_mac_mcp.core.platform import CommandError
from nexus_mac_mcp.tools import system

DISCHARGING = (
    "Now drawing from 'Battery Power'\n"
    " -InternalBattery-0 (id=22872163)\t74%; discharging; 5:24 remaining present: true\n"
)
CHARGING = (
    "Now drawing from 'AC Power'\n"
    " -InternalBattery-0 (id=22872163)\t81%; charging; 1:05 remaining present: true\n"
)
CHARGED = (
    "Now drawing from 'AC Power'\n"
    " -InternalBattery-0 (id=22872163)\t100%; charged; 0:00 remaining present: true\n"
)
NO_ESTIMATE = (
    "Now drawing from 'AC Power'\n"
    " -InternalBattery-0 (id=22872163)\t62%; AC attached; not charging present: true\n"
)
DESKTOP = "Now drawing from 'AC Power'\n"


# --- battery_status --------------------------------------------------------


def test_battery_while_discharging(fake_run) -> None:
    calls = fake_run(system, stdout=DISCHARGING)

    result = system.battery_status()

    assert result["success"] is True
    assert result["percentage"] == 74
    assert result["charging"] is False
    assert result["state"] == "discharging"
    assert result["time_remaining"] == "5:24 remaining"
    assert result["power_source"] == "Battery Power"
    assert result["source"] == "macos"
    assert calls == [["/usr/bin/pmset", "-g", "batt"]]


def test_battery_while_charging(fake_run) -> None:
    fake_run(system, stdout=CHARGING)

    result = system.battery_status()

    assert result["percentage"] == 81
    assert result["charging"] is True
    assert result["power_source"] == "AC Power"


def test_a_full_battery_is_not_reported_as_charging(fake_run) -> None:
    fake_run(system, stdout=CHARGED)

    result = system.battery_status()

    assert result["percentage"] == 100
    assert result["state"] == "charged"
    assert result["charging"] is False


def test_no_time_estimate_is_none_rather_than_junk(fake_run) -> None:
    fake_run(system, stdout=NO_ESTIMATE)

    result = system.battery_status()

    assert result["percentage"] == 62
    assert result["charging"] is False
    # pmset's "present: true" suffix must never leak into the estimate.
    assert result["time_remaining"] is None


def test_a_mac_without_a_battery_reports_failure(fake_run) -> None:
    fake_run(system, stdout=DESKTOP)

    result = system.battery_status()

    assert result == {"success": False, "error": "No battery was found on this Mac."}


def test_a_failing_pmset_becomes_a_structured_error(fake_run) -> None:
    fake_run(system, error=CommandError("/usr/bin/pmset did not respond in time."))

    result = system.battery_status()

    assert result["success"] is False
    assert "did not respond" in result["error"]


@macos_only
def test_battery_reads_this_mac_for_real() -> None:
    result = system.battery_status()

    assert result["success"] is True
    assert 0 <= result["percentage"] <= 100
    assert isinstance(result["charging"], bool)


# --- system_info -----------------------------------------------------------


def test_system_info_shape() -> None:
    result = system.system_info()

    assert result["success"] is True
    assert result["platform"] == "macOS"
    assert result["architecture"]
    assert result["hostname"]
    assert result["python_version"]
    assert result["cpu_count"] >= 1


def test_system_info_withholds_sensitive_details() -> None:
    result = system.system_info()

    # No serial, no user, no network addressing.
    assert not {"serial_number", "user", "username", "ip_address", "mac_address"} & set(
        result
    )
    assert not result["hostname"].endswith(".local")


# --- running_processes -----------------------------------------------------

PS_OUTPUT = """  PID  %CPU %MEM COMM
  408  14.1  0.6 WindowServer
55979   6.2  0.6 Google Chrome Helper
64285   3.9  2.9 Cursor Helper (Renderer)
    1   0.0  0.1 launchd
"""


def test_processes_are_parsed(fake_run) -> None:
    calls = fake_run(system, stdout=PS_OUTPUT)

    result = system.running_processes()

    assert result["success"] is True
    assert result["count"] == 4
    first = result["processes"][0]
    assert first == {
        "pid": 408,
        "cpu_percent": 14.1,
        "memory_percent": 0.6,
        "name": "WindowServer",
    }
    # Names with spaces survive intact.
    assert result["processes"][2]["name"] == "Cursor Helper (Renderer)"
    assert calls == [["/bin/ps", "-Aco", "pid,pcpu,pmem,comm", "-r"]]


def test_process_limit_is_honoured(fake_run) -> None:
    fake_run(system, stdout=PS_OUTPUT)

    result = system.running_processes(limit=2)

    assert result["count"] == 2


def test_process_limit_is_capped(fake_run) -> None:
    fake_run(system, stdout=PS_OUTPUT)

    # Asking for thousands must not dump the whole process table.
    result = system.running_processes(limit=10_000)

    assert result["count"] <= system.MAX_PROCESSES


def test_a_nonsense_limit_is_rejected(fake_run) -> None:
    fake_run(system, stdout=PS_OUTPUT)

    result = system.running_processes(limit=0)

    assert result == {"success": False, "error": "limit must be at least 1."}


def test_processes_report_names_not_command_lines(fake_run) -> None:
    fake_run(system, stdout=PS_OUTPUT)

    result = system.running_processes()

    # Full command lines can carry paths and tokens; they are never returned.
    for process in result["processes"]:
        assert set(process) == {"pid", "cpu_percent", "memory_percent", "name"}


def test_a_failing_ps_becomes_a_structured_error(fake_run) -> None:
    fake_run(system, error=CommandError("/bin/ps failed: nope"))

    result = system.running_processes()

    assert result["success"] is False
    assert "ps" in result["error"]


@macos_only
def test_processes_read_this_mac_for_real() -> None:
    result = system.running_processes(limit=5)

    assert result["success"] is True
    assert 1 <= result["count"] <= 5
    assert all(process["name"] for process in result["processes"])
