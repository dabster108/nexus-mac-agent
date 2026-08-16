"""Evidence → outcome. Pure functions, no I/O, no model.

Each rule takes what the checks actually returned and decides what it proves.
Keeping them pure is what makes "verification is deterministic" a testable
claim rather than a stated intention: every branch below can be exercised
without a Mac, a process or a network.

The bias throughout is towards UNKNOWN. A rule only returns SUCCESS when the
evidence positively confirms the goal; anything short of that is PARTIAL or
UNKNOWN, because an invented SUCCESS is the one failure mode of this whole
phase that would matter.
"""

from __future__ import annotations

from typing import Any

from app.verification.models import Confidence, Evidence, Outcome, Verification

#: Statuses that mean a managed process is alive right now.
_ALIVE = {"RUNNING", "STARTING"}


def _label(process: dict[str, Any]) -> str:
    return str(process.get("label") or process.get("command") or "the process")


# --- process should now be running ------------------------------------------


def process_running(
    tool: str, status: dict[str, Any] | None, service: dict[str, Any] | None
) -> Verification:
    """Did an action that starts something actually leave it running?"""
    evidence: list[Evidence] = []
    unknowns: list[str] = []

    if status is None or not status.get("success"):
        return Verification(
            tool=tool,
            outcome=Outcome.UNKNOWN,
            summary="The process could not be looked up after starting it.",
            unknowns=("whether the process is still running",),
        )

    state = str(status.get("status") or "")
    exit_code = status.get("exit_code")
    evidence.append(
        Evidence.observed("process_status", f"the process reports {state}")
    )

    if state not in _ALIVE:
        detail = f" with exit code {exit_code}" if exit_code is not None else ""
        return Verification(
            tool=tool,
            outcome=Outcome.FAILED,
            evidence=tuple(evidence),
            summary=f"It started but is no longer running — it {state.lower()}{detail}.",
            unknowns=("why it stopped; its logs would say",),
        )

    # Alive. Whether that means *working* depends on there being something to ask.
    if service is None:
        return Verification(
            tool=tool,
            outcome=Outcome.PARTIAL_SUCCESS,
            evidence=tuple(evidence),
            summary="It is running, but there is no endpoint to confirm it is serving.",
            unknowns=("whether it is answering requests",),
        )

    if service.get("reachable"):
        code = service.get("status_code")
        evidence.append(
            Evidence.observed(
                "check_local_service",
                f"{service.get('url')} answered"
                + (f" with HTTP {code}" if code else ""),
            )
        )
        evidence.append(
            Evidence.inferred("verifier", "it is ready to receive requests")
        )
        return Verification(
            tool=tool,
            outcome=Outcome.SUCCESS,
            evidence=tuple(evidence),
            summary="It is running and answering.",
            unknowns=("whether every endpoint behaves correctly",),
        )

    # Running but not answering. Common and legitimate during startup, so this
    # is deliberately not FAILED — the process itself is demonstrably alive.
    evidence.append(
        Evidence.observed(
            "check_local_service",
            f"{service.get('url')} did not answer yet",
            confidence=Confidence.HIGH,
        )
    )
    unknowns.append("whether it is still starting up or genuinely unreachable")
    return Verification(
        tool=tool,
        outcome=Outcome.PARTIAL_SUCCESS,
        evidence=tuple(evidence),
        summary="The process is running, but nothing answered on its port yet.",
        unknowns=tuple(unknowns),
    )


# --- process should now be stopped -------------------------------------------


def process_stopped(tool: str, status: dict[str, Any] | None) -> Verification:
    if status is None or not status.get("success"):
        # The manager forgetting a process is the expected shape of a *successful*
        # stop in some paths, so this is UNKNOWN rather than FAILED.
        return Verification(
            tool=tool,
            outcome=Outcome.UNKNOWN,
            summary="The process could not be looked up after stopping it.",
            unknowns=("whether it is really stopped",),
        )

    state = str(status.get("status") or "")
    evidence = (Evidence.observed("process_status", f"the process reports {state}"),)

    if state in _ALIVE:
        return Verification(
            tool=tool,
            outcome=Outcome.FAILED,
            evidence=evidence,
            summary="It is still running.",
            unknowns=("why it did not stop",),
        )

    return Verification(
        tool=tool,
        outcome=Outcome.SUCCESS,
        evidence=evidence,
        summary="It is stopped.",
    )


# --- a service should now be answering ---------------------------------------


def local_service(tool: str, service: dict[str, Any] | None) -> Verification:
    if service is None or not service.get("success"):
        return Verification(
            tool=tool,
            outcome=Outcome.UNKNOWN,
            summary="The service could not be checked.",
            unknowns=("whether it is answering",),
        )

    url = service.get("url")
    if service.get("reachable"):
        code = service.get("status_code")
        return Verification(
            tool=tool,
            outcome=Outcome.SUCCESS,
            evidence=(
                Evidence.observed(
                    "check_local_service",
                    f"{url} answered" + (f" with HTTP {code}" if code else ""),
                ),
            ),
            summary="It is answering.",
        )

    return Verification(
        tool=tool,
        outcome=Outcome.FAILED,
        evidence=(Evidence.observed("check_local_service", f"nothing answered at {url}"),),
        summary="Nothing answered.",
        unknowns=("whether it was ever started",),
    )


# --- the action's own exit code is the answer --------------------------------


def exit_code(tool: str, result: dict[str, Any]) -> Verification:
    """For commands whose result already proves the outcome.

    Nothing else is run: re-running a test suite to confirm a test suite is
    both wasteful and, for anything with side effects, wrong.
    """
    if not result.get("success"):
        reason = str(result.get("error") or result.get("reason") or "it was refused")
        return Verification(
            tool=tool,
            outcome=Outcome.FAILED,
            evidence=(Evidence.observed(tool, reason),),
            summary="The command did not run.",
        )

    code = result.get("exit_code")
    if code is None:
        return Verification(
            tool=tool,
            outcome=Outcome.UNKNOWN,
            summary="The command ran, but reported no exit code.",
            unknowns=("whether it did what was intended",),
        )

    evidence = (Evidence.observed(tool, f"the command exited with code {code}"),)
    if code == 0:
        return Verification(
            tool=tool,
            outcome=Outcome.SUCCESS,
            evidence=evidence,
            summary="The command succeeded.",
            unknowns=("any effect the command had that its exit code does not cover",),
        )
    return Verification(
        tool=tool,
        outcome=Outcome.FAILED,
        evidence=evidence,
        summary=f"The command failed (exit {code}).",
    )


# --- an application should now be open ---------------------------------------


def application(
    tool: str, name: str, processes: dict[str, Any] | None
) -> Verification:
    """Only presence can be checked — a window is not observable from here,
    and observing one would need the GUI automation this project refuses."""
    unknowns = ("whether the application's window actually opened",)

    if processes is None or not processes.get("success"):
        return Verification(
            tool=tool,
            outcome=Outcome.UNKNOWN,
            summary="The application was launched; its process could not be looked up.",
            unknowns=unknowns,
        )

    needle = (name or "").casefold()
    found = any(
        needle and needle in str(process.get("name", "")).casefold()
        for process in processes.get("processes", [])
    )
    if found:
        return Verification(
            tool=tool,
            outcome=Outcome.SUCCESS,
            evidence=(
                Evidence.observed("running_processes", f"a process named '{name}' is running"),
            ),
            summary=f"{name} is running.",
            unknowns=unknowns,
        )

    return Verification(
        tool=tool,
        outcome=Outcome.UNKNOWN,
        evidence=(
            Evidence.observed(
                "running_processes", f"no process matching '{name}' was found"
            ),
        ),
        summary="The application was launched, but no matching process was found.",
        unknowns=unknowns + ("whether it is still starting",),
    )


__all__ = [
    "application",
    "exit_code",
    "local_service",
    "process_running",
    "process_stopped",
]
