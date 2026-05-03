"""fin_analyst_runner — LangGraph leaf node for the financial analysis workflow.

Architecture
------------
This node is activated for all queries that are NOT the perf-test trigger phrase.
The outer graph routes to this sub-graph for any genuine financial analysis query.

Node pattern (shared with all agents):
    ``interrupt()``  (step-approval checkpoint — auto-approved for now)
    → ``@task``-decorated work function (LangGraph-checkpointed computation)
    → lifecycle events (create_task / complete_task) called inside the task

The ``@task`` decorator from ``langgraph.func`` marks the computation as a
LangGraph subtask.  On resume after a cancel/crash, LangGraph replays the
cached task result rather than re-executing the function body — ensuring
idempotent recovery.

``interrupt()`` from ``langgraph.types`` replaces the former Redis
``check_node_cancel`` call.  The runner auto-approves every interrupt via
``Command(resume=True)``; future human-in-the-loop flows can selectively
decline approval instead.
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
from backend.graph.utils.execution_log import finish_node_execution, start_node_execution
from backend.sse_notifications import (
    TaskCancelledSignal,
    cancel_task,
    complete_task,
    create_task,
    fail_task,
)
from backend.sse_notifications.node import emit_node_status
from backend.graph.agents.fin_analyst.errors import FIN_ANALYST_FAILED
from backend.graph.agents.fin_analyst.models import FinAnalystOutput

logger = logging.getLogger(__name__)

_NODE_NAME: str = "fin_analyst_runner"


@task
async def _analyse_task(
    thread_id: str,
    task_id: str,
    node_execution_id: int,
    node_id: str,
    query: str,
) -> FinAnalystOutput:
    """Inner LangGraph ``@task``: task-level lifecycle only.

    Owns the application task DB record: ``create_task`` → analysis →
    ``complete_task`` / ``cancel_task`` / ``fail_task``.

    Node-level teardown (``finish_node_execution``, ``emit_node_status``
    terminal state) is the responsibility of the outer
    :func:`_run_fin_analyst_node` so that concerns are cleanly separated.
    """
    await create_task(
        thread_id,
        "FIN_ANALYST_ANALYSIS",
        node_execution_id,
        provider="stub",
        task_id=task_id,
        extra_payload={"node_id": node_id},
    )

    try:
        output = await _analyse(query)
    except (asyncio.CancelledError, TaskCancelledSignal):
        await cancel_task(thread_id, task_id, "FIN_ANALYST_ANALYSIS")
        raise asyncio.CancelledError()
    except Exception as exc:
        logger.exception("[fin_analyst] analysis error thread_id=%s: %s", thread_id, exc)
        await fail_task(
            thread_id, task_id, "FIN_ANALYST_ANALYSIS", str(exc),
            error_code=FIN_ANALYST_FAILED,
        )
        raise

    await complete_task(thread_id, task_id, "FIN_ANALYST_ANALYSIS", output.as_dict())
    return output


async def _analyse(query: str) -> FinAnalystOutput:
    """Stub analysis — placeholder until real LLM / market-data integration."""
    # TODO: replace with real market data + LLM pipeline
    return FinAnalystOutput(
        summary=f"[stub] Received query: {query!r}. Full analysis pending implementation.",
        confidence=0.0,
    )


@task
async def _run_fin_analyst_node(
    thread_id: str,
    parent_node_execution_id: int | None,
    query: str,
) -> dict:
    """Outer LangGraph ``@task``: node-level lifecycle and orchestration.

    Owns UUIDs, ``start_node_execution``, ``finish_node_execution``, and
    ``emit_node_status`` for the node.  Delegates analysis + task-level DB
    records to :func:`_analyse_task`.  Checkpointed by LangGraph — on resume
    after cancel, replays the cached result without re-executing.
    """
    node_id: str = str(uuid.uuid4())
    task_id: str = str(uuid.uuid4())
    started_at = datetime.now(timezone.utc)
    t0_node = time.monotonic()

    node_execution_id = await start_node_execution(
        thread_id,
        _NODE_NAME,
        {"query": query, "node_id": node_id, "task_id": task_id},
        started_at,
        node_uuid=node_id,
        parent_node_execution_id=parent_node_execution_id,
    )
    await emit_node_status(thread_id, node_id, _NODE_NAME, "running")

    terminal_status = "completed"
    try:
        output = await _analyse_task(thread_id, task_id, node_execution_id, node_id, query)
    except asyncio.CancelledError:
        terminal_status = "cancelled"
        elapsed_ms = int((time.monotonic() - t0_node) * 1000)
        await finish_node_execution(node_execution_id, {"cancelled": True}, elapsed_ms, status=terminal_status)
        await emit_node_status(thread_id, node_id, _NODE_NAME, terminal_status)
        raise
    except Exception as exc:
        terminal_status = "failed"
        elapsed_ms = int((time.monotonic() - t0_node) * 1000)
        await finish_node_execution(node_execution_id, {"error": str(exc)[:500]}, elapsed_ms, status=terminal_status)
        await emit_node_status(thread_id, node_id, _NODE_NAME, terminal_status)
        raise

    elapsed_ms = int((time.monotonic() - t0_node) * 1000)
    await finish_node_execution(node_execution_id, output.as_dict(), elapsed_ms, status=terminal_status)
    await emit_node_status(thread_id, node_id, _NODE_NAME, terminal_status)

    logger.info(
        "[fin_analyst] completed thread_id=%s node_id=%s elapsed_ms=%d",
        thread_id, node_id, elapsed_ms,
    )
    return {
        "node_execution_id": node_execution_id,
        "node_id": node_id,
        "task_id": task_id,
        "result": output.summary,
    }


async def fin_analyst_runner(state: StreamRunState) -> dict:
    """LangGraph node: checkpoint via ``interrupt()`` then delegate to ``@task``.

    Reading state fields before ``interrupt()`` has no side effects and is
    safe on resume.  All DB writes / SSE emits are inside :func:`_run_fin_analyst_node`.

    Args:
        state: Shared :class:`~backend.graph.state.StreamRunState`.

    Returns:
        Partial state update containing ``node_execution_id``, ``node_id``,
        ``task_id``, and ``result``.
    """
    thread_id: str = state["thread_id"]
    query: str = state.get("query", "")
    parent_node_execution_id: int | None = state.get("node_execution_id")

    interrupt({"action": "step_approval", "node": _NODE_NAME, "thread_id": thread_id})

    return await _run_fin_analyst_node(thread_id, parent_node_execution_id, query)

