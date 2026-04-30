"""Graph runner -- async execution of the LangGraph workflow in the FastAPI event loop.

Each query runs as an ``asyncio.Task`` inside the FastAPI uvicorn event loop.
The graph is a two-level structure:

    POST /api/v1/users/query
      |_ queries.py
           |_ asyncio.create_task(run_graph_async(...))   [FastAPI event loop]
                |_ graph.ainvoke(...)
                     |_ stream_subgraph  (triggered by "DO STREAMING PERFORMANCE TEST NOW")
                     |    |_ stream_runner -> dispatch_throughput_ingest / dispatch_scheduled_ingest -> Celery -> Centrifugo
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
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime

from sqlalchemy import select, update

from backend.api.registry import running_tasks as _running_tasks
from backend.db import get_session_factory as _get_session_factory
from backend.db.redis.session.query_phase import set_query_phase
from backend.db.redis.lock_manager.session_cleanup import cleanup_thread_session
from backend.graph.compiled import get_compiled_graph
from backend.sse_notifications import emit_done
from backend.graph.governance import publish_governance_end
from backend.streaming.errors import GRAPH_EXECUTION_FAILED
from backend.sse_notifications.query_lifecycle import emit_query_status
from backend.users.models import UserQuery

logger = logging.getLogger(__name__)


async def run_graph_async(
    thread_id: str,
    query: str,
) -> None:
    """Run the LangGraph workflow for one query inside the FastAPI event loop.

    Called via ``asyncio.create_task()`` from the query ACK endpoint.  The
    graph routes internally based on ``query`` text:

    * ``"DO STREAMING PERFORMANCE TEST NOW"`` -> streamer sub-graph
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
        final_state = await graph.ainvoke(initial_state, config)
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
