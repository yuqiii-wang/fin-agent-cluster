"""merge_results — NodeTask for merge_node (child of research_subgraph).

This task receives the chained outputs of read_stats and read_news as its
input, demonstrating intra-subgraph task output chaining.
"""

from __future__ import annotations

import logging

from langgraph.func import task

from backend.langgraph.lifecycle import complete_task, create_task
from backend.langgraph.models.models import TaskInput, TaskOutput
from backend.langgraph.models.task import NodeTask
from backend.langgraph.nodes.mock_research_subgraph.tasks.models import MergeInput, MergeOutput
from backend.celery_task.workers.task_delegation import delegate_completion

logger = logging.getLogger(__name__)

_TASK_NAME = "merge_results"


async def _handler(payload: dict) -> dict:
    """Combine stats and news data into a unified research summary.

    Args:
        payload: Serialised ``MergeInput`` dict containing ``stats_data``
            and ``news_data`` from the parallel fetch tasks.

    Returns:
        Serialised ``MergeOutput`` dict.
    """
    inp = MergeInput.model_validate(payload)
    stats = inp.stats_data
    news = inp.news_data
    symbol = stats.get("symbol") or news.get("symbol") or "?"
    n_records = len(stats.get("records", []))
    n_articles = len(news.get("articles", []))
    summary = (
        f"Research summary for {symbol}: "
        f"{n_records} price records and {n_articles} news articles retrieved."
    )
    return MergeOutput(symbol=symbol, summary=summary, stats=stats, news=news).model_dump()


@task
async def _merge_results_task(
    task_input: TaskInput[MergeInput],
) -> TaskOutput[MergeOutput]:
    """LangGraph @task: delegates merge_results to a Celery completion worker.

    Input is constructed from chained read_stats + read_news outputs by the
    parent subgraph's ``orchestrate``.

    Args:
        task_input: Typed envelope with TaskContext and MergeInput content.

    Returns:
        TaskOutput wrapping MergeOutput.
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
    output = MergeOutput.model_validate(result)
    return TaskOutput(ctx=ctx, content=output)


merge_results = NodeTask(
    name=_TASK_NAME,
    description=(
        "Merge OHLCV stats and news articles into a unified research summary "
        "for the equity symbol."
    ),
    input_type=MergeInput,
    output_type=MergeOutput,
    task_fn=_merge_results_task,
    handler=_handler,
)
