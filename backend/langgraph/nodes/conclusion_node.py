"""conclusion_node — final node in the fin-analysis graph.

Hierarchy
---------
Thread
  └── conclusion_node  (Typical)
        └── stream_conclusion  (@task → Celery stream worker)

Responsibilities
----------------
* Build a prompt from the merged research summary.
* Stream LLM tokens through Centrifugo to the frontend WebSocket.
* Persist the full LLM response to ``fin_agents.llm_responses``.
* SSE events: task_status: running/completed, node_status (auto).
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
from backend.celery_task.workers.task_delegation import delegate_stream

logger = logging.getLogger(__name__)

_NODE_NAME = "conclusion_node"
_TASK_NAME = "stream_conclusion"


# ---------------------------------------------------------------------------
# @task: stream_conclusion (streaming)
# ---------------------------------------------------------------------------


@task
async def stream_conclusion(state: GraphState) -> dict[str, Any]:
    """Stream an LLM conclusion and persist the result.

    Tokens flow:
      Celery worker → fin:llm:tokens (Redis Stream)
        → Centrifugo token-streaming tier
          → WebSocket channel ``thread:{thread_id}``
            → UI

    After streaming the full answer is stored in ``fin_agents.llm_responses``
    and the task is marked ``completed``.

    Args:
        state: Current graph state (must include ``merged_research``).

    Returns:
        Partial state: ``{"conclusion": "<full answer text>"}``.
    """
    thread_id: str = state["thread_id"]
    node_id = make_node_id(thread_id, _NODE_NAME)
    task_id = make_task_id()

    payload = {
        "merged_research": state.get("merged_research", {}),
        "query": state.get("query", ""),
    }

    await create_task(thread_id, node_id, _NODE_NAME, task_id, _TASK_NAME, payload)
    try:
        result = await delegate_stream(
            thread_id=thread_id,
            task_id=task_id,
            task_name=_TASK_NAME,
            node_name=_NODE_NAME,
            payload=payload,
        )
        # result = {"answer": str, "total_tokens": int, "latency_ms": int}
        await complete_task(
            thread_id, node_id, _NODE_NAME, task_id, _TASK_NAME,
            output_data=result,
        )
        logger.info(
            "[conclusion_node] stream done thread_id=%s tokens=%d latency_ms=%d",
            thread_id, result.get("total_tokens", 0), result.get("latency_ms", 0),
        )
        return {"conclusion": result.get("answer", "")}
    except Exception as exc:
        await complete_task(
            thread_id, node_id, _NODE_NAME, task_id, _TASK_NAME,
            failed=True, error=str(exc),
        )
        raise


# ---------------------------------------------------------------------------
# Node function
# ---------------------------------------------------------------------------


async def conclusion_node(state: GraphState) -> GraphState:
    """LangGraph node: stream the final LLM conclusion.

    Args:
        state: Current :class:`~backend.langgraph.state.GraphState`.

    Returns:
        Updated state with ``conclusion`` populated.
    """
    thread_id: str = state["thread_id"]
    node_id = make_node_id(thread_id, _NODE_NAME)

    await upsert_node(
        thread_id=thread_id,
        node_id=node_id,
        node_name=_NODE_NAME,
        node_type=NodeType.TYPICAL,
        input_data={"merged_research": state.get("merged_research", {})},
    )

    try:
        future = stream_conclusion(state)
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
