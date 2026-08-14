"""Dependency-graph checks shared by planning and execution.

Steps form a DAG through ``depends_on``. Planning uses this to reject a cyclic
or otherwise malformed plan before a single tool runs; execution uses it to
find the next step that is actually eligible to run.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence


class DependencyCycleError(ValueError):
    """The plan's steps depend on each other in a loop."""


def find_cycle(depends_on: Mapping[str, Sequence[str]]) -> list[str] | None:
    """Return one cycle (as a list of step ids) if the graph has one, else None."""
    WHITE, GRAY, BLACK = 0, 1, 2
    colour: dict[str, int] = dict.fromkeys(depends_on, WHITE)
    path: list[str] = []

    def visit(node: str) -> list[str] | None:
        colour[node] = GRAY
        path.append(node)
        for dep in depends_on.get(node, ()):
            if dep not in colour:
                continue  # dangling references are a separate validation error
            if colour[dep] == GRAY:
                return path[path.index(dep) :] + [dep]
            if colour[dep] == WHITE:
                found = visit(dep)
                if found:
                    return found
        path.pop()
        colour[node] = BLACK
        return None

    for node in depends_on:
        if colour[node] == WHITE:
            found = visit(node)
            if found:
                return found
    return None


def topological_order(depends_on: Mapping[str, Sequence[str]]) -> list[str]:
    """A valid execution order. Raises :class:`DependencyCycleError` if none exists.

    Used only to validate a plan is orderable at all; the engine itself walks
    steps by checking eligibility each iteration, which naturally respects the
    same ordering while also reacting to skip/failure outcomes.
    """
    cycle = find_cycle(depends_on)
    if cycle is not None:
        raise DependencyCycleError(f"Steps depend on each other in a loop: {cycle}")

    ordered: list[str] = []
    remaining = dict(depends_on)
    while remaining:
        ready = [node for node, deps in remaining.items() if not deps or all(
            dep not in remaining for dep in deps
        )]
        if not ready:  # pragma: no cover - find_cycle already ruled this out
            raise DependencyCycleError("Steps depend on each other in a loop.")
        ordered.extend(ready)
        for node in ready:
            del remaining[node]
    return ordered
