"""Proactive observation: noticing what changed, without acting on it.

Re-exports nothing, for the same reason as :mod:`app.context` — the detector
reaches into :mod:`app.tools` and is reached by :mod:`app.agent`, so an eager
import here would put a cycle on every ``app.observations`` import. Import the
submodule you need directly.

The boundary that matters: this package may *observe* and *report*. It calls
SAFE tools only, never the model, and never anything that changes the machine.
Acting on an observation is the user's decision, taken through the ordinary
agent, tool registry and approval broker.
"""
