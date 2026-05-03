"""State schema for the LangGraph workflow (shared across all agents)."""

from __future__ import annotations

from typing import Annotated, NotRequired, Optional, TypedDict


class StreamRunState(TypedDict):
    """Shared state for the multi-agent LangGraph graph.

    ID hierarchy (DB-backed)
    ------------------------
    thread_id → node_execution_id → (parent_node_execution_ids for fan-in nodes)
                                  → task_id → llm_response (optional 1:1)

    Governance hierarchy (Redis-backed)
    ------------------------------------
    thread_id → node_id → task_id → stream_id (optional)

    Fields
    ------
    thread_id               : UUID of the LangGraph run.
    query                   : Raw query text used for agent routing.
    node_execution_id       : DB PK of the most recent node_executions row.
    node_id                 : Governance UUID of the node execution (Redis registry).
    task_id                 : Governance UUID of the task invocation within the node.
    stream_id               : UUID of the streaming session (LLM streams only).
    result                  : Summary string set by the active agent.
    query_response          : Mock JSON response produced by the query node.
    news_articles           : News article dicts fetched by the news node.
    stats_records           : Stats record dicts fetched by the stats node.
    news_node_execution_id  : Execution ID of the news node (for fan-in edge).
    stats_node_execution_id : Execution ID of the stats node (for fan-in edge).
    merged_analysis         : Merged JSON produced by merge_node for analysis_node.
    """

    thread_id: str
    query: str
    node_execution_id: Annotated[Optional[int], lambda _old, new: new]
    node_id: NotRequired[str]
    task_id: NotRequired[str]
    stream_id: NotRequired[str]
    result: NotRequired[str]
    # ── Mock analysis pipeline fields ─────────────────────────────────────────
    query_response: NotRequired[dict]
    news_articles: NotRequired[list[dict]]
    stats_records: NotRequired[list[dict]]
    news_node_execution_id: NotRequired[Optional[int]]
    stats_node_execution_id: NotRequired[Optional[int]]
    merged_analysis: NotRequired[dict]
