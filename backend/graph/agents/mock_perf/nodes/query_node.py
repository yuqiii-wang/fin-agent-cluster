"""query_node — mock query-parser node that produces a structured JSON analysis request.

This node is the entry point for the mock analysis pipeline:

    query_node → [news_node, stats_node] → merge_node

It parses the incoming query string (or uses defaults) and hard-writes a mock
JSON response that subsequent nodes use to scope their data fetches.  In a
production pipeline this would call an LLM to extract entities and parameters.

Trigger phrase: ``"DO MOCK ANALYSIS NOW"`` (case-insensitive prefix).

Refactored to use:
- ``@task`` from ``langgraph.func`` for the computation function so LangGraph
  checkpoints the result and avoids re-execution on resume.
- ``interrupt()`` from ``langgraph.types`` as the step-approval checkpoint,
  replacing the former ``check_node_cancel`` Redis signal.
"""

from __future__ import annotations

import asyncio
import logging
import time
import uuid
from datetime import datetime, timezone

from langgraph.func import task
from langgraph.types import interrupt

from backend.graph.state import StreamRunState
from backend.graph.utils.execution_log import (
    finish_node_execution,
    start_node_execution,
    update_node_execution_status,
)
from backend.sse_notifications import (
    TaskCancelledSignal,
    cancel_task,
    complete_task,
    create_task,
    fail_task,
)
from backend.sse_notifications.node import emit_node_status
from backend.graph.agents.mock_perf.errors import QUERY_FAILED

logger = logging.getLogger(__name__)

_NODE_NAME: str = "mock_query"

# ── Mock JSON response template ────────────────────────────────────────────
# Hard-coded to demonstrate the query-parsing stage without real LLM calls.
_MOCK_QUERY_RESPONSE: dict = {
    "symbol": "AAPL",
    "analysis_type": "comprehensive",
    "time_horizon": "1w",
    "parameters": {
        "limit_news": 5,
        "period": "1d",
        "indicators": ["close", "volume", "sma_20", "rsi_14"],
    },
    "rationale": (
        "Mock analysis request for AAPL covering 1-week horizon with "
        "intraday stats and latest 5 news articles."
    ),
}


@task
async def _parse_query_task(
    thread_id: str,
    task_id: str,
    node_execution_id: int,
    node_id: str,
    query: str,
) -> dict:
    """LangGraph ``@task``: parse query and emit task lifecycle events.

    Result is checkpointed — not re-executed on resume after a cancel/crash.

    Args:
        thread_id:         LangGraph thread UUID.
        task_id:           Task primary-key UUID.
        node_execution_id: FK to the parent ``node_executions`` row.
        node_id:           Node-level UUID for SSE events.
        query:             Raw user query text (unused; future LLM extraction).

    Returns:
        Mock query-response dict (hard-coded for stub purposes).
    """
    await create_task(
        thread_id,
        "QUERY",
        node_execution_id,
        provider="mock",
        task_id=task_id,
        extra_payload={"node_id": node_id},
    )

    try:
        response = dict(_MOCK_QUERY_RESPONSE)
    except (asyncio.CancelledError, TaskCancelledSignal):
        await cancel_task(thread_id, task_id, "QUERY")
        await update_node_execution_status(node_execution_id, "cancelled")
        await emit_node_status(thread_id, node_id, _NODE_NAME, "cancelled")
        raise asyncio.CancelledError()
    except Exception as exc:
        logger.exception("[mock_query] parse error thread_id=%s: %s", thread_id, exc)
        t0_err = time.monotonic()
        await fail_task(thread_id, task_id, "QUERY", str(exc), error_code=QUERY_FAILED)
        await finish_node_execution(node_execution_id, {"error": str(exc)[:500]}, 0, status="failed")
        await emit_node_status(thread_id, node_id, _NODE_NAME, "failed")
        raise

    await complete_task(
        thread_id,
        task_id,
        "QUERY",
        output={"query_response": response},
    )
    return response


async def mock_query_node(state: StreamRunState) -> dict:
    """Parse the query and return a mock JSON analysis response.

    Uses ``interrupt()`` as a step-approval checkpoint (replacing the former
    ``check_node_cancel`` Redis signal) then delegates computation to the
    ``@task``-decorated :func:`_parse_query_task`.

    Args:
        state: :class:`~backend.graph.state.StreamRunState`.

    Returns:
        Partial state update with ``node_id``, ``task_id``,
        and ``query_response``.
    """
    thread_id: str = state["thread_id"]
    parent_node_execution_id: int | None = state.get("node_execution_id")

    # ── Step-approval interrupt (replaces check_node_cancel) ──────────────
    interrupt({"action": "step_approval", "node": _NODE_NAME, "thread_id": thread_id})

    node_id: str = str(uuid.uuid4())
    task_id: str = str(uuid.uuid4())
    started_at = datetime.now(timezone.utc)
    t0 = time.monotonic()

    node_execution_id = await start_node_execution(
        thread_id,
        _NODE_NAME,
        {"query": state.get("query", ""), "node_id": node_id, "task_id": task_id},
        started_at,
        node_uuid=node_id,
        parent_node_execution_id=parent_node_execution_id,
    )
    await emit_node_status(thread_id, node_id, _NODE_NAME, "running")

    try:
        response = await _parse_query_task(thread_id, task_id, node_execution_id, node_id, state.get("query", ""))
    except asyncio.CancelledError:
        elapsed_ms = int((time.monotonic() - t0) * 1000)
        await update_node_execution_status(node_execution_id, "cancelled")
        await emit_node_status(thread_id, node_id, _NODE_NAME, "cancelled")
        raise
    except Exception:
        elapsed_ms = int((time.monotonic() - t0) * 1000)
        await update_node_execution_status(node_execution_id, "failed")
        await emit_node_status(thread_id, node_id, _NODE_NAME, "failed")
        raise

    elapsed_ms = int((time.monotonic() - t0) * 1000)
    await finish_node_execution(node_execution_id, {"query_response": response}, elapsed_ms)
    await emit_node_status(thread_id, node_id, _NODE_NAME, "completed")

    logger.info(
        "[mock_query] completed symbol=%s thread_id=%s node_id=%s elapsed_ms=%d",
        response.get("symbol"), thread_id, node_id, elapsed_ms,
    )
    return {
        "node_execution_id": node_execution_id,
        "node_id": node_id,
        "task_id": task_id,
        "query_response": response,
    }


__all__ = ["mock_query_node"]
