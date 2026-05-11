"""research_subgraph — parallel stats + news fetch followed by a merge node.

Hierarchy
---------
Thread
  └── research_subgraph  (Subgraph node)
        ├── stats_node  (Typical, parent=research_subgraph)
        │     └── read_stats  (@task → Celery completion worker)
        ├── news_node   (Typical, parent=research_subgraph)
        │     └── read_news   (@task → Celery completion worker)
        └── merge_node  (Typical, parent=research_subgraph)
              └── merge_results  (@task → Celery completion worker)

stats_node and news_node run **concurrently** (asyncio.gather).
merge_node runs after both finish.

SSE events emitted
------------------
* task_status: running/completed for each @task
* node_status (auto) for each child node when all its tasks finish
* node_status (auto) for the subgraph node when all child nodes finish
  (node completion is triggered after merge_node completes).
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from langgraph.func import task

from backend.langgraph.state import GraphState
from backend.db.postgres.types import NodeType
from backend.langgraph.lifecycle import (
    complete_node,
    complete_task,
    create_task,
    make_node_id,
    make_task_id,
    upsert_node,
)
from backend.celery_task.workers.task_delegation import delegate_completion

logger = logging.getLogger(__name__)

_SUBGRAPH_NAME = "research_subgraph"
_STATS_NODE = "stats_node"
_NEWS_NODE = "news_node"
_MERGE_NODE = "merge_node"


# ---------------------------------------------------------------------------
# @task: read_stats
# ---------------------------------------------------------------------------


@task
async def read_stats(state: GraphState) -> dict[str, Any]:
    """Fetch market statistics for symbols extracted by query_node.

    Args:
        state: Current graph state (must include ``query_analysis``).

    Returns:
        Partial state: ``{"stats_data": {...}}``.
    """
    thread_id: str = state["thread_id"]
    node_id = make_node_id(thread_id, _STATS_NODE)
    task_id = make_task_id()
    analysis = state.get("query_analysis", {})
    payload = {
        "symbols": analysis.get("symbols", ["AAPL"]),
        "interval": "1d",
    }

    await create_task(thread_id, node_id, _STATS_NODE, task_id, "read_stats", payload)
    try:
        result = await delegate_completion(thread_id, task_id, node_id, _STATS_NODE, "read_stats", payload)
    except Exception as exc:
        # Safety net for TimeoutError / ThreadCancelledError only.
        # Celery worker failures have SSE emitted by delegate_completion.
        await complete_task(
            thread_id, node_id, _STATS_NODE, task_id, "read_stats",
            failed=True, error=str(exc),
        )
        raise
    return {"stats_data": result}


# ---------------------------------------------------------------------------
# @task: read_news
# ---------------------------------------------------------------------------


@task
async def read_news(state: GraphState) -> dict[str, Any]:
    """Fetch recent news articles for symbols extracted by query_node.

    Args:
        state: Current graph state (must include ``query_analysis``).

    Returns:
        Partial state: ``{"news_data": {...}}``.
    """
    thread_id: str = state["thread_id"]
    node_id = make_node_id(thread_id, _NEWS_NODE)
    task_id = make_task_id()
    analysis = state.get("query_analysis", {})
    payload = {"symbols": analysis.get("symbols", ["AAPL"])}

    await create_task(thread_id, node_id, _NEWS_NODE, task_id, "read_news", payload)
    try:
        result = await delegate_completion(thread_id, task_id, node_id, _NEWS_NODE, "read_news", payload)
    except Exception as exc:
        # Safety net for TimeoutError / ThreadCancelledError only.
        await complete_task(
            thread_id, node_id, _NEWS_NODE, task_id, "read_news",
            failed=True, error=str(exc),
        )
        raise
    return {"news_data": result}


# ---------------------------------------------------------------------------
# @task: merge_results
# ---------------------------------------------------------------------------


@task
async def merge_results(state: GraphState) -> dict[str, Any]:
    """Combine stats and news data into a unified research summary.

    Args:
        state: Current graph state (must include ``stats_data`` + ``news_data``).

    Returns:
        Partial state: ``{"merged_research": {...}}``.
    """
    thread_id: str = state["thread_id"]
    node_id = make_node_id(thread_id, _MERGE_NODE)
    task_id = make_task_id()
    payload = {
        "stats_data": state.get("stats_data", {}),
        "news_data": state.get("news_data", {}),
    }

    await create_task(thread_id, node_id, _MERGE_NODE, task_id, "merge_results", payload)
    try:
        result = await delegate_completion(thread_id, task_id, node_id, _MERGE_NODE, "merge_results", payload)
    except Exception as exc:
        # Safety net for TimeoutError / ThreadCancelledError only.
        await complete_task(
            thread_id, node_id, _MERGE_NODE, task_id, "merge_results",
            failed=True, error=str(exc),
        )
        raise
    return {"merged_research": result}


# ---------------------------------------------------------------------------
# Individual child-node runners (called inside the subgraph function)
# ---------------------------------------------------------------------------


async def _run_stats_node(state: GraphState, subgraph_node_id: str) -> dict[str, Any]:
    thread_id: str = state["thread_id"]
    node_id = make_node_id(thread_id, _STATS_NODE)
    await upsert_node(
        thread_id=thread_id,
        node_id=node_id,
        node_name=_STATS_NODE,
        node_type=NodeType.TYPICAL,
        parent_node_id=subgraph_node_id,
        input_data=state.get("query_analysis", {}),
    )
    try:
        future = read_stats(state)
        result = await future
    except Exception as exc:
        await complete_node(
            thread_id=thread_id,
            node_id=node_id,
            node_name=_STATS_NODE,
            failed=True,
            error=str(exc),
        )
        raise
    await complete_node(
        thread_id=thread_id,
        node_id=node_id,
        node_name=_STATS_NODE,
        output_data=result,
    )
    return result


async def _run_news_node(state: GraphState, subgraph_node_id: str) -> dict[str, Any]:
    thread_id: str = state["thread_id"]
    node_id = make_node_id(thread_id, _NEWS_NODE)
    await upsert_node(
        thread_id=thread_id,
        node_id=node_id,
        node_name=_NEWS_NODE,
        node_type=NodeType.TYPICAL,
        parent_node_id=subgraph_node_id,
        input_data=state.get("query_analysis", {}),
    )
    try:
        future = read_news(state)
        result = await future
    except Exception as exc:
        await complete_node(
            thread_id=thread_id,
            node_id=node_id,
            node_name=_NEWS_NODE,
            failed=True,
            error=str(exc),
        )
        raise
    await complete_node(
        thread_id=thread_id,
        node_id=node_id,
        node_name=_NEWS_NODE,
        output_data=result,
    )
    return result


# ---------------------------------------------------------------------------
# Subgraph node function (entry point for the main graph)
# ---------------------------------------------------------------------------


async def research_subgraph(state: GraphState) -> GraphState:
    """LangGraph node: parallel stats + news fetch, then merge.

    Registered as a ``Subgraph`` node in Postgres.  Its three child nodes
    (stats_node, news_node, merge_node) are registered as ``Typical`` nodes
    with ``parent_node_id`` pointing to this subgraph.

    Execution order:
      1. stats_node + news_node run concurrently via ``asyncio.gather``.
      2. Their results are merged into state.
      3. merge_node runs with the combined data.

    Args:
        state: Current :class:`~backend.langgraph.state.GraphState`.

    Returns:
        Updated state with ``stats_data``, ``news_data``, and
        ``merged_research`` populated.
    """
    thread_id: str = state["thread_id"]
    subgraph_node_id = make_node_id(thread_id, _SUBGRAPH_NAME)

    # Register the subgraph container node.
    await upsert_node(
        thread_id=thread_id,
        node_id=subgraph_node_id,
        node_name=_SUBGRAPH_NAME,
        node_type=NodeType.SUBGRAPH,
        input_data=state.get("query_analysis", {}),
    )

    # ── Step 1: stats + news in parallel ──────────────────────────────
    try:
        stats_result, news_result = await asyncio.gather(
            _run_stats_node(state, subgraph_node_id),
            _run_news_node(state, subgraph_node_id),
        )
    except Exception as exc:
        # stats_node or news_node already marked itself failed.
        # Propagate failure up to the subgraph container node and stop.
        await complete_node(
            thread_id=thread_id,
            node_id=subgraph_node_id,
            node_name=_SUBGRAPH_NAME,
            failed=True,
            error=str(exc),
        )
        raise

    # ── Step 2: merge (sequential, depends on both above) ─────────────
    merged_state: GraphState = {**state, **stats_result, **news_result}
    merge_node_id = make_node_id(thread_id, _MERGE_NODE)
    await upsert_node(
        thread_id=thread_id,
        node_id=merge_node_id,
        node_name=_MERGE_NODE,
        node_type=NodeType.TYPICAL,
        parent_node_id=subgraph_node_id,
        input_data={
            "stats_data": merged_state.get("stats_data", {}),
            "news_data": merged_state.get("news_data", {}),
        },
    )

    merge_exc: Exception | None = None
    merge_result: dict[str, Any] = {}
    try:
        merge_result = await merge_results(merged_state)
    except Exception as exc:
        merge_exc = exc

    # ── Multi-hop: notify merge_node AND parent subgraph concurrently ──
    # merge_node is the last child node; once it reaches a terminal state
    # the subgraph container is also terminal.  Firing both SSE notifications
    # concurrently halves the ACK-wait cost compared to sequential calls.
    if merge_exc is not None:
        await asyncio.gather(
            complete_node(
                thread_id=thread_id,
                node_id=merge_node_id,
                node_name=_MERGE_NODE,
                failed=True,
                error=str(merge_exc),
            ),
            complete_node(
                thread_id=thread_id,
                node_id=subgraph_node_id,
                node_name=_SUBGRAPH_NAME,
                failed=True,
                error=str(merge_exc),
            ),
            return_exceptions=True,
        )
        raise merge_exc

    final_state: GraphState = {**merged_state, **merge_result}
    await asyncio.gather(
        complete_node(
            thread_id=thread_id,
            node_id=merge_node_id,
            node_name=_MERGE_NODE,
            output_data=merge_result,
        ),
        complete_node(
            thread_id=thread_id,
            node_id=subgraph_node_id,
            node_name=_SUBGRAPH_NAME,
            output_data={"merged_research": final_state.get("merged_research", {})},
        ),
    )

    return final_state
