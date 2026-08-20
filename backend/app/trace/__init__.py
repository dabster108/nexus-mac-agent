"""Explainable execution traces.

Re-exports nothing, like the other leaf packages, so importing it cannot close
a cycle. Import the submodule directly.

The invariant: a trace is a *projection* of events that actually fired. It is
read-only, deterministic, and contains no field capable of holding model
reasoning — so there is no path by which hidden chain-of-thought reaches one.
"""
