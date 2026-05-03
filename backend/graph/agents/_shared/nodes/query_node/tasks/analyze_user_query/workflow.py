"""workflow — async task function for the query parsing stage.

Encapsulates the full task lifecycle (``create_task`` → parse → ``complete_task``)
so :func:`~backend.graph.agents._shared.nodes.query_node.node.query_node` stays
a thin orchestrator.

When *query* starts with ``"DO E2E TEST NOW"`` (case-insensitive) the task
calls :class:`~backend.llm.providers.mock.E2EMockChatModel` and parses its
JSON response.  All other queries fall through to the configured real LLM
(not yet implemented — raises ``NotImplementedError``).
"""

from __future__ import annotations

import asyncio
import json
import logging

from langchain_core.messages import HumanMessage
from langgraph.func import task

from backend.graph.agents._shared.errors import QUERY_FAILED
from backend.graph.agents._shared.nodes.query_node.tasks.analyze_user_query.models import QueryTaskOutput
from backend.llm.providers.mock.fixtures import E2E_TRIGGER
from backend.sse_notifications import (
    TaskCancelledSignal,
    cancel_task,
    complete_task,
    create_task,
    fail_task,
)

logger = logging.getLogger(__name__)


@task
async def run_analyze_user_query_task(
    thread_id: str,
    task_id: str,
    node_execution_id: int,
    node_id: str,
    *,
    query: str = "",
) -> QueryTaskOutput:
    """Parse the incoming query and return a structured analysis request.

    Creates a DB task row (``analyze_user_query`` key), performs the parse (mock), then
    marks it completed.  Raises on cancel / error so the caller
    (:func:`~backend.graph.agents._shared.nodes.query_node.node.query_node`) can
    handle node-level teardown.

    Args:
        thread_id:         LangGraph thread UUID.
        task_id:           Pre-generated task UUID passed as ``extra_payload``.
        node_execution_id: FK to the parent ``node_executions`` row.
        node_id:           Node governance UUID (passed to extra_payload).
        query:             Raw query text from graph state.

    Returns:
        :class:`~backend.graph.agents._shared.nodes.query_node.tasks.analyze_user_query.models.QueryTaskOutput`
        containing the structured analysis request.

    Raises:
        asyncio.CancelledError: Propagated from cancel / TaskCancelledSignal.
        Exception:              Any unexpected parse failure.
    """
    await asyncio.sleep(0)  # yield to event loop before task creation

    await create_task(
        thread_id,
        "analyze_user_query",
        node_execution_id,
        provider="mock",
        task_id=task_id,
        extra_payload={"node_id": node_id},
    )

    try:
        if query.upper().startswith(E2E_TRIGGER):
            from backend.llm.providers.mock import get_e2e_mock_llm  # noqa: PLC0415
            llm = get_e2e_mock_llm()
            response = await llm.ainvoke([HumanMessage(content=query)])
            raw = json.loads(response.content)
            logger.debug("[query_task] e2e mock response symbol=%s", raw.get("symbol"))
        else:
            raise NotImplementedError(
                f"[query_task] real LLM extraction not yet implemented for query: {query!r}"
            )
        output = QueryTaskOutput(**raw)
    except (asyncio.CancelledError, TaskCancelledSignal):
        await cancel_task(thread_id, task_id, "analyze_user_query")
        raise asyncio.CancelledError()
    except Exception as exc:
        logger.exception(
            "[query_task] parse failed thread_id=%s: %s", thread_id, exc
        )
        await fail_task(thread_id, task_id, "analyze_user_query", str(exc), error_code=QUERY_FAILED)
        raise

    await complete_task(
        thread_id,
        task_id,
        "analyze_user_query",
        output={"query_response": output.as_dict()},
    )

    logger.debug(
        "[query_task] completed symbol=%s thread_id=%s",
        output.symbol, thread_id,
    )
    return output


__all__ = ["run_analyze_user_query_task"]
