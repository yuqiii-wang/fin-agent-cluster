"""fin_analyst_runner — LangGraph leaf node for the financial analysis workflow.

Architecture
------------
This node is activated for all queries that are NOT the perf-test trigger phrase.
The outer graph routes to this sub-graph for any genuine financial analysis query.

Node pattern (shared with all agents):
    ``create_task()`` (DB INSERT + emit ``started``)
    → analysis work
    → ``complete_task()`` (DB UPDATE + emit ``completed``)
    → return result

This is a stub implementation.  Real analysis logic (market data, LLM calls,
decision-making) will be added as the feature matures.
"""

from __future__ import annotations

import logging
import time
import uuid
from datetime import datetime, timezone

from backend.graph.agents.task_keys import FIN_ANALYST_ANALYSIS
from backend.graph.state import StreamRunState
from backend.graph.utils.execution_log import finish_node_execution, start_node_execution
from backend.sse_notifications import (
    TaskCancelledSignal,
    cancel_task,
    complete_task,
    create_task,
    fail_task,
)
from backend.graph.agents.fin_analyst.errors import FIN_ANALYST_FAILED
from backend.graph.agents.fin_analyst.models import FinAnalystOutput

logger = logging.getLogger(__name__)

_NODE_NAME: str = "fin_analyst_runner"


async def fin_analyst_runner(state: StreamRunState) -> dict:
    """Leaf node — run financial analysis and emit lifecycle events.

    Generates ``node_id`` and ``leaf_node_id`` UUIDs included in the ``started``
    SSE event so the frontend can display the full execution hierarchy.

    Args:
        state: Shared :class:`~backend.graph.state.StreamRunState`.

    Returns:
        Partial state update containing ``node_id``, ``leaf_node_id``,
        ``task_id``, and ``result``.
    """
    import asyncio  # noqa: PLC0415 — local import avoids top-level asyncio dep

    thread_id: str = state["thread_id"]
    query: str = state.get("query", "")

    node_id: str = str(uuid.uuid4())
    leaf_node_id: str = str(uuid.uuid4())
    started_at = datetime.now(timezone.utc)
    t0_node = time.monotonic()

    node_execution_id = await start_node_execution(
        thread_id,
        _NODE_NAME,
        {"query": query, "node_id": node_id, "leaf_node_id": leaf_node_id},
        started_at,
    )

    task_id = await create_task(
        thread_id,
        FIN_ANALYST_ANALYSIS,
        node_execution_id,
        provider="stub",
        extra_payload={"node_id": node_id, "leaf_node_id": leaf_node_id},
    )

    try:
        output = await _analyse(query)
    except (asyncio.CancelledError, TaskCancelledSignal):
        elapsed_ms = int((time.monotonic() - t0_node) * 1000)
        await cancel_task(thread_id, task_id, FIN_ANALYST_ANALYSIS)
        await finish_node_execution(node_execution_id, {"cancelled": True}, elapsed_ms)
        raise asyncio.CancelledError()
    except Exception as exc:
        elapsed_ms = int((time.monotonic() - t0_node) * 1000)
        logger.exception("[fin_analyst] analysis error thread_id=%s: %s", thread_id, exc)
        await fail_task(
            thread_id, task_id, FIN_ANALYST_ANALYSIS, str(exc),
            error_code=FIN_ANALYST_FAILED,
        )
        await finish_node_execution(node_execution_id, {"error": str(exc)[:500]}, elapsed_ms)
        raise

    elapsed_ms = int((time.monotonic() - t0_node) * 1000)
    await complete_task(thread_id, task_id, FIN_ANALYST_ANALYSIS, output.as_dict())
    await finish_node_execution(node_execution_id, output.as_dict(), elapsed_ms)

    logger.info(
        "[fin_analyst] completed thread_id=%s elapsed_ms=%d",
        thread_id,
        elapsed_ms,
    )
    return {
        "node_id": node_id,
        "leaf_node_id": leaf_node_id,
        "task_id": task_id,
        "result": output.summary,
    }


async def _analyse(query: str) -> FinAnalystOutput:
    """Stub analysis — placeholder until real LLM / market-data integration.

    Args:
        query: The user's raw query text.

    Returns:
        A :class:`~backend.graph.agents.fin_analyst.models.FinAnalystOutput`
        with a canned summary and confidence score.
    """
    # TODO: replace with real market data + LLM pipeline
    return FinAnalystOutput(
        summary=f"[stub] Received query: {query!r}. Full analysis pending implementation.",
        confidence=0.0,
    )
