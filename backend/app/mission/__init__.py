"""The mission engine: multi-step objectives, orchestrated over the existing
single-task agent runtime rather than a second security or execution system.

Re-exports nothing, for the same reason as :mod:`app.agent`: the engine
imports the context collector, which imports ``app.agent``, which imports the
runner, which imports this package. Import the submodule directly.
"""
