"""Entry point.

Started by the NEXUS backend as a child process and spoken to over stdio:

    python -m nexus_mac_mcp

It is a local capability server. It has no network listener and must never be
given one.
"""

from __future__ import annotations

import signal
from contextlib import suppress

from nexus_mac_mcp.core.platform import require_macos


def _install_shutdown_handlers() -> None:
    """Stop managed processes when this server is told to exit.

    Without this, killing the backend would leave its development servers
    running with nothing tracking them — orphaned `npm run dev` processes that
    the user then has to hunt down by hand.
    """
    from nexus_mac_mcp.core.process_manager import get_process_manager

    def handle(signum: int, _frame: object) -> None:
        get_process_manager().shutdown_all()
        raise SystemExit(128 + signum)

    for sig in (signal.SIGTERM, signal.SIGINT, signal.SIGHUP):
        with suppress(ValueError, OSError):  # not the main thread
            signal.signal(sig, handle)


def main() -> None:
    require_macos()
    # Imported after the platform check so the failure is the clear message
    # above rather than something odd from a macOS-only code path.
    from nexus_mac_mcp.server import server

    _install_shutdown_handlers()
    try:
        server.run("stdio")
    finally:
        from nexus_mac_mcp.core.process_manager import get_process_manager

        get_process_manager().shutdown_all()


if __name__ == "__main__":
    main()
