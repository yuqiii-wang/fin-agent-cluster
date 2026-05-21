"""stream_llm — streaming LLM NodeTask for conclusion_node.

This is a streaming task: it uses ``delegate_stream`` instead of
``delegate_completion``.  Unlike non-streaming tasks (where the Celery
worker calls ``persist_task_result``), the streaming path requires an
explicit ``complete_task`` call on success in the @task function.

Execution layers
----------------
LangGraph layer (``_stream_llm_task``):
    Calls ``create_task``, delegates to the streaming Celery worker via
    ``delegate_stream``, calls ``complete_task`` with the full result on
    success, and calls ``complete_task(failed=True)`` on exception.

Celery layer (``_handler``):
    Pure async function: builds the LLM prompt from the merged research
    summary and streams tokens through Centrifugo to the frontend.
    Returns the full answer text with token count and latency.
"""

from __future__ import annotations

import json
import logging

from langgraph.func import task

from backend.langgraph.lifecycle import complete_task, create_task
from backend.langgraph.models.models import TaskInput, TaskOutput
from backend.langgraph.models.task import NodeTask
from backend.langgraph.nodes.mock_conclusion_node.models import ConclusionNodeInput, ConclusionNodeOutput
from backend.celery_task.workers.task_delegation import delegate_stream

logger = logging.getLogger(__name__)

_TASK_NAME = "stream_llm"


async def _handler(payload: dict) -> dict:
    """Build an LLM prompt from merged research and stream the conclusion.

    Tokens flow:
      Celery worker → fin:llm:tokens (Redis Stream)
        → Centrifugo token-streaming tier
          → WebSocket channel ``thread:{thread_id}``
            → UI

    Args:
        payload: Serialised ``ConclusionNodeInput`` dict.

    Returns:
        Serialised ``ConclusionNodeOutput`` dict.
    """
    # Handler body is implemented in the Celery stream worker.
    # This stub is present for structural consistency — the actual
    # logic lives in celery_task/workers/tasks/stream_task.py.
    raise NotImplementedError("stream_llm handler runs in the streaming Celery worker.")


@task
async def _stream_llm_task(
    task_input: TaskInput[ConclusionNodeInput],
) -> TaskOutput[ConclusionNodeOutput]:
    """LangGraph @task: delegates stream_llm to the streaming Celery worker.

    Streaming tasks require an explicit ``complete_task`` call on success
    because the streaming Celery worker does not call ``persist_task_result``
    the same way non-streaming workers do.

    Args:
        task_input: Typed envelope with TaskContext and ConclusionNodeInput content.

    Returns:
        TaskOutput wrapping ConclusionNodeOutput.
    """
    ctx = task_input.ctx
    payload = task_input.content.model_dump()

    await create_task(ctx.thread_id, ctx.node_id, ctx.node_name, ctx.task_id, ctx.task_name, payload, view_type="Streaming")
    try:
        result = await delegate_stream(
            thread_id=ctx.thread_id,
            task_id=ctx.task_id,
            task_name=ctx.task_name,
            node_name=ctx.node_name,
            payload=payload,
        )
        # result["answer"] is a dict (parsed JSON) returned by the streaming worker.
        # Defensively parse it if the worker returned a raw string.
        raw_answer = result.get("answer", {})
        if isinstance(raw_answer, str):
            try:
                answer_dict = json.loads(raw_answer)
            except (json.JSONDecodeError, TypeError):
                logger.error(
                    "[stream_llm] answer JSON parse failed task_id=%s; storing raw text",
                    ctx.task_id,
                )
                answer_dict = {"raw": raw_answer}
        else:
            answer_dict = raw_answer
        output = ConclusionNodeOutput(
            answer=answer_dict,
            thinking=result.get("thinking"),
            total_tokens=result.get("total_tokens", 0),
            latency_ms=result.get("latency_ms", 0),
        )
        await complete_task(
            ctx.thread_id, ctx.node_id, ctx.node_name, ctx.task_id, ctx.task_name,
            output_data=output.model_dump(),
            view_type="Streaming",
        )
        return TaskOutput(ctx=ctx, content=output)
    except Exception as exc:
        await complete_task(
            ctx.thread_id, ctx.node_id, ctx.node_name, ctx.task_id, ctx.task_name,
            failed=True, error=str(exc), view_type="Streaming",
        )
        raise


stream_llm = NodeTask(
    name=_TASK_NAME,
    description=(
        "Stream an LLM-generated conclusion based on the merged research summary "
        "and original user query. Tokens are streamed to the frontend via Centrifugo."
    ),
    input_type=ConclusionNodeInput,
    output_type=ConclusionNodeOutput,
    task_fn=_stream_llm_task,
    handler=_handler,
)

__all__ = ["stream_llm"]
