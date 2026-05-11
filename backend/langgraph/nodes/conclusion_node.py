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
    BaseNodeInput,
    BaseNodeOutput,
    BaseTaskInput,
    BaseTaskOutput,
    MergeResultsOutput,
    StreamConclusionInput,
    StreamConclusionOutput,
)
from backend.celery_task.workers.task_delegation import delegate_stream

logger = logging.getLogger(__name__)

_NODE_NAME = "conclusion_node"
_TASK_NAME = "stream_conclusion"


# ---------------------------------------------------------------------------
# @task: stream_conclusion (streaming)
# ---------------------------------------------------------------------------


@task
async def stream_conclusion(
    task_input: BaseTaskInput[StreamConclusionInput],
) -> BaseTaskOutput[StreamConclusionOutput]:
    """Stream an LLM conclusion and persist the result.

    Tokens flow:
      Celery worker → fin:llm:tokens (Redis Stream)
        → Centrifugo token-streaming tier
          → WebSocket channel ``thread:{thread_id}``
            → UI

    After streaming the full answer is stored in ``fin_agents.llm_responses``
    and the task is marked ``completed``.

    Args:
        task_input: Typed envelope carrying thread/node/task identity and
            the :class:`StreamConclusionInput` content.

    Returns:
        :class:`BaseTaskOutput` wrapping the :class:`StreamConclusionOutput`.
    """
    thread_id = task_input.thread_id
    node_id = task_input.node_id
    task_id = task_input.task_id
    payload = task_input.content.model_dump()

    await create_task(thread_id, node_id, _NODE_NAME, task_id, _TASK_NAME, payload)
    try:
        result = await delegate_stream(
            thread_id=thread_id,
            task_id=task_id,
            task_name=_TASK_NAME,
            node_name=_NODE_NAME,
            payload=payload,
        )
        output_content = StreamConclusionOutput.model_validate(result)
        await complete_task(
            thread_id, node_id, _NODE_NAME, task_id, _TASK_NAME,
            output_data=output_content.model_dump(),
        )
        return BaseTaskOutput[StreamConclusionOutput](
            thread_id=thread_id,
            node_id=node_id,
            task_id=task_id,
            task_name=_TASK_NAME,
            content=output_content,
        )
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
    task_id = make_task_id()

    merged_research = MergeResultsOutput.model_validate(
        state.get("merged_research", {})
    )
    conclusion_input = StreamConclusionInput(
        merged_research=merged_research.model_dump(),
        query=state.get("query", ""),
    )

    node_input = BaseNodeInput[StreamConclusionInput](
        thread_id=thread_id,
        node_id=node_id,
        node_name=_NODE_NAME,
        content=conclusion_input,
    )

    await upsert_node(
        thread_id=thread_id,
        node_id=node_id,
        node_name=_NODE_NAME,
        node_type=NodeType.TYPICAL,
        input_data=node_input.content.model_dump(),
    )

    task_input = BaseTaskInput[StreamConclusionInput](
        thread_id=thread_id,
        node_id=node_id,
        task_id=task_id,
        task_name=_TASK_NAME,
        content=conclusion_input,
    )

    try:
        task_output: BaseTaskOutput[StreamConclusionOutput] = await stream_conclusion(task_input)
    except Exception as exc:
        await complete_node(
            thread_id=thread_id,
            node_id=node_id,
            node_name=_NODE_NAME,
            failed=True,
            error=str(exc),
        )
        raise

    node_output = BaseNodeOutput[StreamConclusionOutput](
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
    return {**state, "conclusion": node_output.content.answer}
