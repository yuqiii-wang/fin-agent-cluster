"""read_stats — NodeTask for stats_node (child of research_subgraph)."""

from __future__ import annotations

import logging

from langgraph.func import task

from backend.langgraph.lifecycle import complete_task, create_task
from backend.langgraph.nodes.base.models import TaskInput, TaskOutput
from backend.langgraph.nodes.base.task import NodeTask
from backend.langgraph.nodes.research_subgraph.tasks.models import ReadStatsInput, ReadStatsOutput
from backend.celery_task.workers.task_delegation import delegate_completion

logger = logging.getLogger(__name__)

_TASK_NAME = "read_stats"


async def _handler(payload: dict) -> dict:
    """Fetch OHLCV market statistics for the first symbol in *payload*.

    Args:
        payload: Serialised ``ReadStatsInput`` dict.

    Returns:
        Serialised ``ReadStatsOutput`` dict.
    """
    from backend.resources.stats.client import StatsClient

    inp = ReadStatsInput.model_validate(payload)
    symbol = (inp.symbols or ["AAPL"])[0]
    client = StatsClient()
    try:
        response = await client.list_stats(symbol, inp.interval)
        records = [r.model_dump(mode="json") for r in response.items]
    finally:
        await client.aclose()
    return ReadStatsOutput(symbol=symbol, interval=inp.interval, records=records).model_dump()


@task
async def _read_stats_task(
    task_input: TaskInput[ReadStatsInput],
) -> TaskOutput[ReadStatsOutput]:
    """LangGraph @task: delegates read_stats to a Celery completion worker.

    Args:
        task_input: Typed envelope with TaskContext and ReadStatsInput content.

    Returns:
        TaskOutput wrapping ReadStatsOutput.
    """
    ctx = task_input.ctx
    payload = task_input.content.model_dump()

    await create_task(ctx.thread_id, ctx.node_id, ctx.node_name, ctx.task_id, ctx.task_name, payload)
    try:
        result = await delegate_completion(
            ctx.thread_id, ctx.task_id, ctx.node_id, ctx.node_name, ctx.task_name, payload
        )
    except Exception as exc:
        await complete_task(
            ctx.thread_id, ctx.node_id, ctx.node_name, ctx.task_id, ctx.task_name,
            failed=True, error=str(exc),
        )
        raise
    output = ReadStatsOutput.model_validate(result)
    return TaskOutput(ctx=ctx, content=output)


read_stats = NodeTask(
    name=_TASK_NAME,
    description="Fetch OHLCV market statistics for the given equity symbols.",
    input_type=ReadStatsInput,
    output_type=ReadStatsOutput,
    task_fn=_read_stats_task,
    handler=_handler,
)
