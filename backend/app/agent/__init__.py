"""The LangGraph agent: state, nodes, graph, runtime.

This package re-exports nothing. Importing the runner here put it on the path
of every ``app.agent`` import, including ``from app.agent import events`` —
and the runner reaches the mission engine and the context collector, both of
which import back into this package. The result was that whichever module a
process happened to import first decided whether the application started.

Import the submodule you need directly (``app.agent.runner``,
``app.agent.events``, ...), which is what every caller already does.
"""
