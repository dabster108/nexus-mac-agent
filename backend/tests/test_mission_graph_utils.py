"""Dependency-graph checks used by planning and execution."""

from __future__ import annotations

import pytest

from app.mission.graph_utils import DependencyCycleError, find_cycle, topological_order


def test_no_cycle_in_a_line() -> None:
    assert find_cycle({"a": [], "b": ["a"], "c": ["b"]}) is None


def test_no_cycle_with_no_dependencies() -> None:
    assert find_cycle({"a": [], "b": [], "c": []}) is None


def test_a_direct_cycle_is_found() -> None:
    cycle = find_cycle({"a": ["b"], "b": ["a"]})
    assert cycle is not None
    assert set(cycle) == {"a", "b"}


def test_a_self_reference_is_a_cycle() -> None:
    cycle = find_cycle({"a": ["a"]})
    assert cycle == ["a", "a"]


def test_an_indirect_cycle_is_found() -> None:
    cycle = find_cycle({"a": ["b"], "b": ["c"], "c": ["a"]})
    assert cycle is not None
    assert set(cycle) == {"a", "b", "c"}


def test_a_dangling_reference_is_not_a_cycle() -> None:
    # Missing dependencies are a separate validation concern (unknown step id).
    assert find_cycle({"a": ["ghost"]}) is None


def test_topological_order_respects_dependencies() -> None:
    order = topological_order({"a": [], "b": ["a"], "c": ["b"]})

    assert order.index("a") < order.index("b") < order.index("c")


def test_topological_order_handles_a_diamond() -> None:
    order = topological_order({"a": [], "b": ["a"], "c": ["a"], "d": ["b", "c"]})

    assert order.index("a") < order.index("b")
    assert order.index("a") < order.index("c")
    assert order.index("b") < order.index("d")
    assert order.index("c") < order.index("d")


def test_topological_order_raises_on_a_cycle() -> None:
    with pytest.raises(DependencyCycleError):
        topological_order({"a": ["b"], "b": ["a"]})
