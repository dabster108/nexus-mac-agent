"""LangGraph wiring.

    START -> agent -> tools required?
                       ├── no  -> END
                       └── yes -> tools -> agent

Dependencies (model provider, tool registry, permission policy) are bound into
the node functions here, so the graph itself stays free of vendor specifics.
"""

from __future__ import annotations

from functools import partial
from typing import Any

from langgraph.graph import END, START, StateGraph

from app.agent.nodes import (
    SYSTEM_PROMPT,
    after_tools,
    agent_node,
    should_continue,
    tool_node,
)
from app.agent.approvals import ApprovalBroker
from app.agent.events import EventSink, no_sink
from app.agent.state import AgentState
from app.models.base import ModelProvider
from app.tools.permissions import PermissionPolicy
from app.tools.registry import ToolRegistry

AGENT_NODE = "agent"
TOOL_NODE = "tools"


def build_agent_graph(
    *,
    provider: ModelProvider,
    registry: ToolRegistry,
    policy: PermissionPolicy,
    broker: ApprovalBroker | None = None,
    emit: EventSink = no_sink,
    max_iterations: int = 6,
    timeout: float = 60.0,
    permission_timeout: float = 300.0,
    system_prompt: str = SYSTEM_PROMPT,
) -> Any:
    """Compile the NEXUS agent graph.

    ``emit`` receives events as they happen rather than when a node returns,
    which is what lets a client see (and answer) a permission request while the
    tool node is still blocked on it.
    """
    graph = StateGraph(AgentState)

    graph.add_node(
        AGENT_NODE,
        partial(
            agent_node,
            provider=provider,
            registry=registry,
            max_iterations=max_iterations,
            timeout=timeout,
            emit=emit,
            system_prompt=system_prompt,
        ),
    )
    graph.add_node(
        TOOL_NODE,
        partial(
            tool_node,
            registry=registry,
            policy=policy,
            timeout=timeout,
            broker=broker,
            permission_timeout=permission_timeout,
            emit=emit,
        ),
    )

    graph.add_edge(START, AGENT_NODE)
    graph.add_conditional_edges(
        AGENT_NODE,
        partial(should_continue, max_iterations=max_iterations),
        {"tools": TOOL_NODE, "end": END},
    )
    graph.add_conditional_edges(
        TOOL_NODE,
        after_tools,
        {"agent": AGENT_NODE, "end": END},
    )

    return graph.compile()
