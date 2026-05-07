"""Graph runner -- async execution of the LangGraph workflow in the FastAPI event loop.

Each query runs as an ``asyncio.Task`` inside the FastAPI uvicorn event loop.
The graph is a two-level structure:

    POST /api/v1/users/query
      |_ queries.py
           |_ asyncio.create_task(run_graph_async(...))   [FastAPI event loop]
                |_ graph.ainvoke(...)
                     |_ stream_subgraph  (triggered by "DO STREAMING PERFORMANCE TEST NOW")
                     |    |_ mock_runner -> dispatch_throughput_ingest / dispatch_scheduled_ingest -> Celery -> Centrifugo
                     |_ fin_analyst_subgraph  (all other queries)
                          |_ fin_analyst_runner

Lifecycle events
----------------
``started / completed / failed`` are written to PostgreSQL and published to
Redis Pub/Sub by the agent utilities.  The ``done`` terminal event is emitted
here after the graph finishes.

Cancellation
------------
Cancel requests come from ``POST /api/v1/users/query/{thread_id}/cancel``.
Cancel stops the asyncio.Task immediately (CancelledError), yields empty
output, and does NOT trigger resume.

Interrupts (human-in-the-loop)
-------------------------------
Nodes call ``interrupt(value)`` from ``langgraph.types`` at step-approval
checkpoints.  ``graph.ainvoke()`` returns the current state with an
``__interrupt__`` key when execution is paused.  The runner auto-approves
every interrupt **unless** a pause signal is pending (see above).
See :func:`_invoke_with_auto_approve`.

Checkpoints & resume
---------------------
The ``AsyncPostgresSaver`` checkpointer saves graph state:
- *Before* each node is entered — so ``input=None`` (or ``Command(resume=…)``)
  resumes from the last saved state.
- After ``@task``-decorated subtask results — so ``@task`` bodies are
  *never* re-executed on resume; LangGraph loads their cached outputs from the checkpoint.

Calling ``graph.ainvoke(Command(resume=True), config)`` resumes a *paused*
graph from the interrupt checkpoint — the interrupted node continues.
Calling ``graph.ainvoke(None, config)`` resumes a *cancelled/crashed* graph
from the last pre-node checkpoint — the node re-runs from scratch.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select, update

from langgraph.types import Command

from backend.api.registry import running_tasks as _running_tasks
from backend.db import get_session_factory as _get_session_factory
from backend.db.redis.session.query_phase import set_query_phase
from backend.db.redis.lock_manager.session_cleanup import cleanup_thread_session
from backend.graph.compiled import get_compiled_graph
from backend.graph.models import AgentTask
from backend.sse_notifications import emit_done, publish_task_lifecycle
from backend.sse_notifications.node import emit_graph_topology
from backend.graph.governance import publish_governance_end
from backend.streaming.errors import GRAPH_EXECUTION_FAILED
from backend.sse_notifications.thread import emit_query_status
from backend.users.models import UserQuery

logger = logging.getLogger(__name__)


async def _invoke_with_auto_approve(
    graph: Any,
    initial_input: Any,
    config: dict,
) -> dict:
    """Invoke a LangGraph graph, auto-approving all ``interrupt()`` checkpoints.

    Nodes call ``interrupt(value)`` from ``langgraph.types`` at step-approval
    boundaries.  ``ainvoke`` returns the current state with an ``__interrupt__``
    key when such a boundary is hit.  This helper resumes immediately with
    ``Command(resume=True)`` so execution continues without manual intervention.

    A cancelled ``asyncio.Task`` (triggered by ``cancel_query``) propagates
    naturally — ``CancelledError`` is raised from the ``ainvoke`` call and
    exits this loop.

    Args:
        graph:         The compiled LangGraph ``CompiledStateGraph``.
        initial_input: Initial state dict for a fresh run, or ``None`` for
                       resuming from the last saved checkpoint.
        config:        LangGraph run config (must include ``thread_id``).

    Returns:
        The final state dict once all nodes have completed.
    """
    state: Any = initial_input
    while True:
        result: dict = await graph.ainvoke(state, config)
        if "__interrupt__" not in result:
            return result
        # Auto-approve: immediately resume from the interrupt checkpoint.
        state = Command(resume=True)


async def run_graph_async(
    thread_id: str,
    query: str,
) -> None:
    """Run the LangGraph workflow for one query inside the FastAPI event loop.

    Called via ``asyncio.create_task()`` from the query ACK endpoint.  The
    graph routes internally based on ``query`` text:

    * ``"DO STREAMING PERFORMANCE TEST NOW"`` -> mock sub-graph
    * all other queries -> fin_analyst sub-graph

    After natural completion, the governance registry is swept for any streams
    that were not deregistered (e.g. due to a worker crash) and a
    ``stream_stopped`` event is published for each so the frontend receives
    a clean terminal event.

    Lifecycle:
        1. Transition phase to ``preparing``.
        2. Invoke the routed graph (outer -> agent sub-graph -> leaf node).
        3. Update ``UserQuery`` status and emit ``done`` when finished.
        4. Sweep governance registry for orphaned live streams.

    Args:
        thread_id: LangGraph UUID already persisted to the DB.
        query:     Raw query text, used for agent routing.
    """
    factory = _get_session_factory()
    try:
        # Transition phase to "preparing" as soon as the task is scheduled.
        # This signals to the frontend that the request is being processed.
        await set_query_phase(thread_id, "preparing")
        await emit_query_status(thread_id, "preparing")
        # Emit static graph topology so the frontend can pre-populate
        # subgraph container nodes before any node events arrive.
        await emit_graph_topology(thread_id)

        graph = get_compiled_graph()
        config = {
            "configurable": {
                "thread_id": thread_id,
                "checkpoint_ns": "",
            }
        }
        initial_state = {
            "thread_id": thread_id,
            "query": query,
        }
        final_state = await _invoke_with_auto_approve(graph, initial_state, config)

        report = final_state.get("result") or "Stream completed"
        # Remove from running_tasks SYNCHRONOUSLY before any further awaits.
        # This closes the race window where the frontend safety-timeout fires
        # cancel_query after natural completion.
        _running_tasks.pop(thread_id, None)

        # Atomically claim ownership of the done transition.  Using WHERE
        # status='running' means only one writer (runner or cancel endpoint)
        # can commit and emit done -- whoever commits second touches 0 rows
        # and skips emit_done entirely, preventing duplicate done events.
        async with factory() as session:
            result = await session.execute(
                update(UserQuery)
                .where(
                    UserQuery.thread_id == thread_id,
                    UserQuery.status == "running",
                )
                .values(
                    status="completed",
                    answer=report,
                    completed_at=datetime.utcnow(),
                )
                .returning(UserQuery.thread_id)
            )
            claimed = result.fetchone() is not None
            await session.commit()
        if claimed:
            await emit_done(thread_id, "completed", report)
            # Sweep for any streams that did not deregister (worker crash, etc.)
            # and emit stream_stopped so the frontend has a terminal event.
            await publish_governance_end(thread_id, reason="completed")

        await cleanup_thread_session(thread_id)
        logger.info("[graph_runner] completed thread_id=%s", thread_id)

    except asyncio.CancelledError:
        # Cancel endpoint has already updated DB + emitted done; nothing to do.
        await cleanup_thread_session(thread_id)
        logger.info("[graph_runner] cancelled thread_id=%s", thread_id)
        raise

    except Exception as exc:
        logger.exception(
            "[graph_runner] error thread_id=%s: %s",
            thread_id,
            exc,
        )
        # Guard: only update if not already cancelled/completed by the cancel endpoint.
        try:
            async with factory() as session:
                uq = await session.scalar(
                    select(UserQuery).where(UserQuery.thread_id == thread_id)
                )
                if uq is not None and uq.status not in ("cancelled", "failed", "completed"):
                    await session.execute(
                        update(UserQuery)
                        .where(UserQuery.thread_id == thread_id)
                        .values(status="failed", error=str(exc)[:1000])
                    )
                    await session.commit()
                    await emit_done(thread_id, "failed", str(exc), error_code=GRAPH_EXECUTION_FAILED)
                    # Sweep governance for any orphaned streams on error path.
                    await publish_governance_end(thread_id, reason="failed")
        except Exception as cleanup_exc:
            logger.warning(
                "[graph_runner] cleanup error thread_id=%s: %s",
                thread_id,
                cleanup_exc,
            )
        await cleanup_thread_session(thread_id)


async def run_resume_async(thread_id: str) -> None:
    """Resume a previously-cancelled LangGraph run from its last checkpoint.

    Passes ``input=None`` to :func:`_invoke_with_auto_approve` so LangGraph
    loads the most recent ``AsyncPostgresSaver`` checkpoint and re-runs the
    interrupted node from its beginning.  All lifecycle handling is identical
    to :func:`run_graph_async`.

    Checkpoint resume
    -----------------
    ``@task``-decorated subtask results that were already checkpointed before
    the cancel are loaded by LangGraph from cache without re-executing the task body —
    only the node that was interrupted at its boundary gets re-run from scratch.

    Args:
        thread_id: LangGraph UUID of the query to resume.
    """
    factory = _get_session_factory()
    try:
        await set_query_phase(thread_id, "preparing")
        await emit_query_status(thread_id, "preparing")
        await emit_graph_topology(thread_id)

        graph = get_compiled_graph()
        config = {
            "configurable": {
                "thread_id": thread_id,
                "checkpoint_ns": "",
            }
        }
        # input=None tells LangGraph to resume from the last saved checkpoint.
        final_state = await _invoke_with_auto_approve(graph, None, config)

        report = (final_state or {}).get("result") or "Stream completed"
        _running_tasks.pop(thread_id, None)

        async with factory() as session:
            result = await session.execute(
                update(UserQuery)
                .where(
                    UserQuery.thread_id == thread_id,
                    UserQuery.status == "running",
                )
                .values(
                    status="completed",
                    answer=report,
                    completed_at=datetime.utcnow(),
                )
                .returning(UserQuery.thread_id)
            )
            claimed = result.fetchone() is not None
            await session.commit()
        if claimed:
            await emit_done(thread_id, "completed", report)
            await publish_governance_end(thread_id, reason="completed")

        await cleanup_thread_session(thread_id)
        logger.info("[graph_runner] resumed_completed thread_id=%s", thread_id)

    except asyncio.CancelledError:
        await cleanup_thread_session(thread_id)
        logger.info("[graph_runner] resumed_cancelled thread_id=%s", thread_id)
        raise

    except Exception as exc:
        logger.exception(
            "[graph_runner] resume_error thread_id=%s: %s",
            thread_id,
            exc,
        )
        try:
            async with factory() as session:
                uq = await session.scalar(
                    select(UserQuery).where(UserQuery.thread_id == thread_id)
                )
                if uq is not None and uq.status not in ("cancelled", "failed", "completed"):
                    await session.execute(
                        update(UserQuery)
                        .where(UserQuery.thread_id == thread_id)
                        .values(status="failed", error=str(exc)[:1000])
                    )
                    await session.commit()
                    await emit_done(thread_id, "failed", str(exc), error_code=GRAPH_EXECUTION_FAILED)
                    await publish_governance_end(thread_id, reason="failed")
        except Exception as cleanup_exc:
            logger.warning(
                "[graph_runner] resume_cleanup_error thread_id=%s: %s",
                thread_id,
                cleanup_exc,
            )
        await cleanup_thread_session(thread_id)
