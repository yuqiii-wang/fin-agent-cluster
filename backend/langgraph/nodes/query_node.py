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
from backend.langgraph.models import (
    AnalyzeQueryInput,
    AnalyzeQueryOutput,
    BaseNodeInput,
    BaseNodeOutput,
    BaseTaskInput,
    BaseTaskOutput,
)
from backend.celery_task.workers.task_delegation import delegate_completion

logger = logging.getLogger(__name__)

_NODE_NAME = "query_node"


# ---------------------------------------------------------------------------
# @task: analyze_query
# ---------------------------------------------------------------------------


@task
async def analyze_query(
    task_input: BaseTaskInput[AnalyzeQueryInput],
) -> BaseTaskOutput[AnalyzeQueryOutput]:
    """Extract intent and equity symbols from the user query.

    Delegates to the Celery completion worker (``run_completion`` with
    ``task_name="analyze_query"``).  The LangGraph thread blocks in a
    thread-pool executor until the worker returns.

    Args:
        task_input: Typed envelope carrying thread/node/task identity and
            the :class:`AnalyzeQueryInput` content.

    Returns:
        :class:`BaseTaskOutput` wrapping the :class:`AnalyzeQueryOutput`.
    """
    thread_id = task_input.thread_id
    node_id = task_input.node_id
    task_id = task_input.task_id
    payload = task_input.content.model_dump()

    await create_task(thread_id, node_id, _NODE_NAME, task_id, "analyze_query", payload)
    try:
        result = await delegate_completion(
            thread_id, task_id, node_id, _NODE_NAME, "analyze_query", payload
        )
    except Exception as exc:
        await complete_task(
            thread_id, node_id, _NODE_NAME, task_id, "analyze_query",
            failed=True, error=str(exc),
        )
        raise
    output_content = AnalyzeQueryOutput.model_validate(result)
    return BaseTaskOutput[AnalyzeQueryOutput](
        thread_id=thread_id,
        node_id=node_id,
        task_id=task_id,
        task_name="analyze_query",
        content=output_content,
    )


# ---------------------------------------------------------------------------
# Node function
# ---------------------------------------------------------------------------


async def query_node(state: GraphState) -> GraphState:
    """LangGraph node: run analyze_query and return updated state.

    Node lifecycle: upsert → run @task → auto-complete via lifecycle module.

    Args:
        state: Current :class:`~backend.langgraph.state.GraphState`.

    Returns:
        Partial state dict with ``query_analysis`` populated as a serialised
        :class:`AnalyzeQueryOutput` dict.
    """
    thread_id: str = state["thread_id"]
    node_id = make_node_id(thread_id, _NODE_NAME)
    task_id = make_task_id()

    node_input = BaseNodeInput[AnalyzeQueryInput](
        thread_id=thread_id,
        node_id=node_id,
        node_name=_NODE_NAME,
        content=AnalyzeQueryInput(query=state.get("query", "")),
    )

    await upsert_node(
        thread_id=thread_id,
        node_id=node_id,
        node_name=_NODE_NAME,
        node_type=NodeType.TYPICAL,
        input_data=node_input.content.model_dump(),
    )

    task_input = BaseTaskInput[AnalyzeQueryInput](
        thread_id=thread_id,
        node_id=node_id,
        task_id=task_id,
        task_name="analyze_query",
        content=node_input.content,
    )

    try:
        task_output: BaseTaskOutput[AnalyzeQueryOutput] = await analyze_query(task_input)
    except Exception as exc:
        await complete_node(
            thread_id=thread_id,
            node_id=node_id,
            node_name=_NODE_NAME,
            failed=True,
            error=str(exc),
        )
        raise

    node_output = BaseNodeOutput[AnalyzeQueryOutput](
        thread_id=thread_id,
        node_id=node_id,
        node_name=_NODE_NAME,
        content=task_output.content,
    )

    await complete_node(
        thread_id=thread_id,
        node_id=node_id,
        node_name=_NODE_NAME,
        output_data=node_output.content.model_dump(),
    )
    return {**state, "query_analysis": node_output.content.model_dump()}

