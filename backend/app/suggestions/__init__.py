"""Proactive suggestion: offering a next step, never taking one.

Re-exports nothing, like :mod:`app.observations` and :mod:`app.context`, so no
import of this package can close a cycle.

The boundary this package must never cross: a suggestion is a sentence offered
to a person. Accepting one produces an ordinary chat message, which the
existing agent answers using the existing tool registry, under the existing
permission policy and approval broker. Nothing here calls a tool, and nothing
here can.
"""
