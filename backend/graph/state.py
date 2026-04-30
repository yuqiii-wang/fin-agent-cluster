"""State schema for the LangGraph workflow (shared across all agents)."""

from __future__ import annotations

from typing import NotRequired, TypedDict


class StreamRunState(TypedDict):
    """Shared state for the multi-agent LangGraph graph.

    The outer graph routes to the appropriate sub-graph based on ``query``.
    Each agent sub-graph populates ``node_id``, ``leaf_node_id``, ``task_id``,
    ``stream_id`` (where applicable), and ``result`` at runtime.

    Fields
    ------
    thread_id    : UUID of the LangGraph run (generated at query submit).
    query        : Raw query text used for agent routing and processing.
    node_id      : UUID of the sub-graph node execution (set by agent node).
    leaf_node_id : UUID of the leaf node execution (set by agent node).
    task_id      : DB primary-key of the ``fin_agents.tasks`` row.
    stream_id    : UUID of the streaming session (set by streamer agent).
    result       : Summary string set by the active agent after completion.
    """

    thread_id: str
    query: str
    node_id: NotRequired[str]
    leaf_node_id: NotRequired[str]
    task_id: NotRequired[int]
    stream_id: NotRequired[str]
    result: NotRequired[str]
