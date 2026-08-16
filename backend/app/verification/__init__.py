"""Closed-loop verification: did the action achieve what was asked?

Re-exports nothing, like :mod:`app.observations` and :mod:`app.suggestions`,
so importing this package cannot close a cycle. Import the submodule directly.

The invariant this package exists to hold: *the tool succeeded* and *the goal
was achieved* are different claims. Only the first is free. Everything here is
read-only, deterministic and bounded — it observes, and never acts.
"""
