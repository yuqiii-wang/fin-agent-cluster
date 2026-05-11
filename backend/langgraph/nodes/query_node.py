"""query_node — first node in the fin-analysis graph.

Hierarchy
---------
Thread
  └── query_node  (Typical)
        └── analyze_query  (@task → Celery completion worker)

Responsibilities
----------------
* Parse the raw user query to extract intent and symbols.
* Persist the node + task rows in Postgres.
* SSE events: task_status: running/completed, node_status (auto via lifecycle).
"""

from __future__ import annotations

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

_NODE_NAME = "query_node"


# ---------------------------------------------------------------------------
# @task: analyze_query
# ---------------------------------------------------------------------------


@task
async def analyze_query(state: GraphState) -> dict[str, Any]:
    """Extract intent and equity symbols from the user query.

    Delegates to the Celery completion worker (``run_completion`` with
    ``task_name="analyze_query"``).  The LangGraph thread blocks in a
    thread-pool executor until the worker returns.

    Args:
        state: Current :class:`~backend.langgraph.state.GraphState`.

    Returns:
        Partial state update: ``{"query_analysis": {...}}``.
    """
    thread_id: str = state["thread_id"]
    node_id = make_node_id(thread_id, _NODE_NAME)
    task_id = make_task_id()

    payload = {"query": state.get("query", "")}

    await create_task(thread_id, node_id, _NODE_NAME, task_id, "analyze_query", payload)
    try:
        result = await delegate_completion(thread_id, task_id, node_id, _NODE_NAME, "analyze_query", payload)
    except Exception as exc:
        # Safety net for TimeoutError and ThreadCancelledError: Celery either
        # did not run or was revoked before persisting.  complete_task writes
        # the DB + emits SSE for these cases.  For Celery worker failures,
        # delegate_completion already fired the task SSE as a background task
        # and Celery wrote the DB, so complete_task is a DB no-op here.
        await complete_task(
            thread_id, node_id, _NODE_NAME, task_id, "analyze_query",
            failed=True, error=str(exc),
        )
        raise
    return {"query_analysis": result}


# ---------------------------------------------------------------------------
# Node function
# ---------------------------------------------------------------------------


async def query_node(state: GraphState) -> GraphState:
    """LangGraph node: run analyze_query and return updated state.

    Node lifecycle: upsert → run @task → auto-complete via lifecycle module.

    Args:
        state: Current :class:`~backend.langgraph.state.GraphState`.

    Returns:
        Partial state dict with ``query_analysis`` populated.
    """
    thread_id: str = state["thread_id"]
    node_id = make_node_id(thread_id, _NODE_NAME)

    await upsert_node(
        thread_id=thread_id,
        node_id=node_id,
        node_name=_NODE_NAME,
        node_type=NodeType.TYPICAL,
        input_data={"query": state.get("query", "")},
    )

    # Run the @task and await its future.
    try:
        future = analyze_query(state)
        result: dict[str, Any] = await future
    except Exception as exc:
        await complete_node(
            thread_id=thread_id,
            node_id=node_id,
            node_name=_NODE_NAME,
            failed=True,
            error=str(exc),
        )
        raise

    await complete_node(
        thread_id=thread_id,
        node_id=node_id,
        node_name=_NODE_NAME,
        output_data=result,
    )
    return {**state, **result}
