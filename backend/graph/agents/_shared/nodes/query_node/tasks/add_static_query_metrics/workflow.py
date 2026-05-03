from __future__ import annotations

import asyncio
import logging

from langgraph.func import task

from backend.graph.agents._shared.nodes.query_node.tasks.analyze_user_query.models import QueryTaskOutput
from backend.graph.agents._shared.nodes.query_node.tasks.add_static_query_metrics.models import AddStaticQueryMetricsOutput
from backend.sse_notifications import cancel_task, complete_task, create_task, fail_task, TaskCancelledSignal

logger = logging.getLogger(__name__)

@task
async def run_add_static_query_metrics_task(
    thread_id: str,
    task_id: str,
    node_execution_id: int,
    node_id: str,
    query_output: QueryTaskOutput,
) -> AddStaticQueryMetricsOutput:
    """Task to add static query metrics (commodities, cryptos)."""
    await asyncio.sleep(0)

    await create_task(
        thread_id,
        "add_static_query_metrics",
        node_execution_id,
        provider="mock",
        task_id=task_id,
        extra_payload={"node_id": node_id},
    )

    try:
        # Append static data
        query_output.commodities = ["gold", "silver", "copper", "oil", "gas"]
        query_output.cryptos = ["bitcoin"]
        out = AddStaticQueryMetricsOutput(**query_output.model_dump())
    except (asyncio.CancelledError, TaskCancelledSignal):
        await cancel_task(thread_id, task_id, "add_static_query_metrics")
        raise asyncio.CancelledError()
    except Exception as exc:
        logger.exception("[add_static_query_metrics] failed thread_id=%s: %s", thread_id, exc)
        await fail_task(thread_id, task_id, "add_static_query_metrics", str(exc), error_code="METRICS_FAILED")
        raise

    await complete_task(
        thread_id,
        task_id,
        "add_static_query_metrics",
        output={"query_response": out.as_dict()},
    )

    logger.debug("[add_static_query_metrics] completed static append thread_id=%s", thread_id)
    return out
