"""read_news — NodeTask for news_node (child of research_subgraph)."""

from __future__ import annotations

import logging

from langgraph.func import task

from backend.langgraph.lifecycle import complete_task, create_task
from backend.langgraph.models.models import TaskInput, TaskOutput
from backend.langgraph.models.task import NodeTask
from backend.langgraph.nodes.mock_research_subgraph.tasks.models import ReadNewsInput, ReadNewsOutput
from backend.celery_task.workers.task_delegation import delegate_completion

logger = logging.getLogger(__name__)

_TASK_NAME = "read_news"


async def _handler(payload: dict) -> dict:
    """Fetch recent news articles for the first symbol in *payload*.

    Args:
        payload: Serialised ``ReadNewsInput`` dict.

    Returns:
        Serialised ``ReadNewsOutput`` dict.
    """
    from backend.resources.news.client import NewsClient

    inp = ReadNewsInput.model_validate(payload)
    symbol = (inp.symbols or ["AAPL"])[0]
    client = NewsClient()
    try:
        response = await client.list_news(symbol=symbol, limit=5)
        articles = [a.model_dump(mode="json") for a in response.items]
    finally:
        await client.aclose()
    return ReadNewsOutput(symbol=symbol, articles=articles).model_dump()


@task
async def _read_news_task(
    task_input: TaskInput[ReadNewsInput],
) -> TaskOutput[ReadNewsOutput]:
    """LangGraph @task: delegates read_news to a Celery completion worker.

    Args:
        task_input: Typed envelope with TaskContext and ReadNewsInput content.

    Returns:
        TaskOutput wrapping ReadNewsOutput.
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
    output = ReadNewsOutput.model_validate(result)
    return TaskOutput(ctx=ctx, content=output)


read_news = NodeTask(
    name=_TASK_NAME,
    description="Fetch recent news articles for the given equity symbols.",
    input_type=ReadNewsInput,
    output_type=ReadNewsOutput,
    task_fn=_read_news_task,
    handler=_handler,
)
