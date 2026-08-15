"""Structured context: memory, workspace and machine state assembled before
the agent runs.

This package deliberately re-exports nothing. Its modules sit at the bottom of
a cycle — the collector and the memory-event wrapper both reach into
:mod:`app.agent` for the event vocabulary, :mod:`app.agent` imports the runner,
and the runner reaches the mission engine, which comes back here. Any eager
import in this file puts that loop on the path of *every* ``app.context``
import, so which module happens to be imported first decides whether the
application starts.

Import the submodule you need directly (``app.context.collector``,
``app.context.models``, ...), which is what every caller already does.
"""
