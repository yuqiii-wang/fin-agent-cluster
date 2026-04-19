"""Graph runner — async execution of the unified LangGraph workflow.

Runs inside the FastAPI event loop as an ``asyncio.Task`` (dispatched by
``backend/api/queries.py``).  LLM calls, DB I/O, and Redis XADD are all
I/O-bound coroutines so cooperative multitasking on the FastAPI event loop
provides genuine parallelism across concurrent requests.

Token flow
----------
LangGraph nodes write tokens to ``tokens:<thread_id>`` via ``stream_token()``
(XADD) directly from within the coroutine running on the FastAPI event loop.
The SSE endpoint reads them independently via ``XREAD BLOCK`` — no coupling
between this runner and the SSE path.

Lifecycle events
----------------
``started / completed / failed`` task rows are written to PostgreSQL by the
LangGraph agent utilities (``create_task / complete_task / fail_task``).  The
``done`` terminal event is emitted here after the graph finishes.

Cancellation
------------
Cancel requests come from ``POST /api/v1/users/query/{thread_id}/cancel``.
The cancel endpoint calls ``task.cancel()`` on the asyncio.Task stored in
``running_tasks``.  The resulting ``CancelledError`` propagates into the graph;
the cancel endpoint also updates the DB and emits ``done`` directly so the
runner does not have to.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime

from sqlalchemy import select, update

from backend.db import checkpointer, get_session_factory as _get_session_factory
from backend.graph import build_unified_graph
from backend.sse_notifications import emit_done
from backend.users.models import UserQuery

logger = logging.getLogger(__name__)


async def run_graph_async(
    thread_id: str,
    query: str,
) -> None:
    """Run the unified LangGraph workflow for one query.

    Routes to the fin-analysis pipeline or the perf-test node based on
    ``query``.  Called via ``asyncio.create_task()`` from the FastAPI query
    endpoint so it never blocks the event loop.

    Lifecycle:
        1. Build + compile the unified graph with a LangGraph checkpointer.
        2. Invoke to completion; nodes XADD tokens to ``tokens:<thread_id>``.
        3. Update ``UserQuery`` status + ``emit_done`` when finished.
        4. Status guards prevent double-updating when the cancel endpoint has
           already closed the query before the graph finishes.

    Args:
        thread_id: LangGraph UUID already persisted to the DB.
        query:     Raw user query string.  If it equals ``PERF_TEST_TRIGGER``
                   the perf-test branch runs; the perf-test node uses its own
                   internal defaults for token count / timeout.
    """
    factory = _get_session_factory()
    try:
        async with checkpointer() as cp:
            graph = build_unified_graph().compile(checkpointer=cp)
            config = {
                "configurable": {
                    "thread_id": thread_id,
                    "checkpoint_ns": "",
                }
            }
            # Provide defaults for every field in UnifiedGraphState so both
            # branches (fin-analysis and perf-test) find their keys present.
            # Fields unused by the active branch are simply ignored.
            initial_state = {
                "query": query,
                "thread_id": thread_id,
                "steps": [],
                "ticker": "",
                "ticker_indexes": [],
                "peer_tickers": [],
                "market_data_input": {},
                "market_data_output": {},
                "market_data": "",
                "fundamental_analysis": "",
                "technical_analysis": "",
                "risk_assessment": "",
                "report": "",
            }
            final_state = await graph.ainvoke(initial_state, config)
            # Perf-test branch stores its summary in ``result``; fin-analysis
            # in ``report`` (with ``market_data`` as a fallback legacy field).
            report = (
                final_state.get("result")
                or final_state.get("report")
                or final_state.get("market_data")
                or "No report generated"
            )

        # Guard: only update if the cancel endpoint has not already closed this query.
        async with factory() as session:
            uq = await session.scalar(
                select(UserQuery).where(UserQuery.thread_id == thread_id)
            )
            if uq is not None and uq.status not in ("cancelled", "failed", "completed"):
                await session.execute(
                    update(UserQuery)
                    .where(UserQuery.thread_id == thread_id)
                    .values(
                        status="completed",
                        answer=report,
                        completed_at=datetime.utcnow(),
                    )
                )
                await session.commit()
                await emit_done(thread_id, "completed", report)

        logger.info("[graph_runner] completed thread_id=%s", thread_id)

    except asyncio.CancelledError:
        # Cancel endpoint has already updated DB + emitted done; nothing to do.
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
                    await emit_done(thread_id, "failed", str(exc))
        except Exception as cleanup_exc:
            logger.warning(
                "[graph_runner] cleanup error thread_id=%s: %s",
                thread_id,
                cleanup_exc,
            )
