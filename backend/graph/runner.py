"""Graph runner — async execution of the unified LangGraph workflow in the FastAPI event loop.

Architecture
------------
Each query runs as an ``asyncio.Task`` inside the FastAPI uvicorn event loop.
All LLM calls, DB I/O, and Redis XADD are I/O-bound coroutines, so cooperative
multitasking provides real parallelism between concurrent queries without any
subprocess or thread pool:

    POST /api/v1/users/query
      └─ queries.py
           └─ asyncio.create_task(run_graph_async(...))   [FastAPI event loop]
                └─ graph.ainvoke(...)
                     └─ LangGraph nodes
                          └─ LLM chain.astream()  →  stream_token() XADD
                               └─ Redis Stream tokens:<thread_id>
                                    └─ SSE generator XREAD BLOCK (independent)

Celery workers handle **only** the Redis Streams batch consumers
(``backend.streaming.workers.*``).  Graph execution is NOT a Celery task.

Token flow
----------
LangGraph nodes write tokens to ``tokens:<thread_id>`` via ``stream_token()``
(XADD) directly inside the asyncio coroutine.  The SSE endpoint reads them
independently via ``XREAD BLOCK`` — no coupling between this runner and the
SSE path.

Lifecycle events
----------------
``started / completed / failed`` task rows are written to PostgreSQL by the
LangGraph agent utilities (``create_task / complete_task / fail_task``).  The
``done`` terminal event is emitted here after the graph finishes.

Cancellation
------------
Cancel requests come from ``POST /api/v1/users/query/{thread_id}/cancel``.
The cancel endpoint calls ``task.cancel()`` on the ``asyncio.Task`` stored in
``running_tasks``.  The cancel endpoint also updates the DB and emits ``done``
so the runner does not have to handle those.
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
from backend.sse_notifications.query_lifecycle import emit_query_status
from backend.users.models import UserQuery

logger = logging.getLogger(__name__)


async def run_graph_async(
    thread_id: str,
    query: str,
    perf_total_tokens: int = 100_000,
    perf_timeout_secs: int = 20,
    perf_test_mode: str = "throughput",
    perf_token_per_sec: int = 500,
) -> None:
    """Run the unified LangGraph workflow for one query inside the FastAPI event loop.

    Routes to the fin-analysis pipeline or the perf-test node based on
    ``query``.  Called via ``asyncio.create_task()`` from the query endpoint.

    Lifecycle:
        1. Build + compile the unified graph with a LangGraph checkpointer.
        2. Invoke to completion; nodes XADD tokens to ``tokens:<thread_id>``.
        3. Update ``UserQuery`` status + ``emit_done`` when finished.
        4. Status guards prevent double-updating when the cancel endpoint has
           already closed the query before the graph finishes.

    Args:
        thread_id:           LangGraph UUID already persisted to the DB.
        query:               Raw user query string.  If it equals ``PERF_TEST_TRIGGER``
                             the perf-test branch runs.
        perf_total_tokens:   Tokens per stream (throughput mode only).
        perf_timeout_secs:   Hard deadline in seconds (both modes).
        perf_test_mode:      ``"throughput"`` or ``"concurrency"``.
        perf_token_per_sec:  Target ingest rate per second (concurrency mode only).
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
                # Perf-test fields — used only when query == PERF_TEST_TRIGGER.
                "total_tokens": perf_total_tokens,
                "timeout_secs": perf_timeout_secs,
                "test_mode": perf_test_mode,
                "token_per_sec": perf_token_per_sec,
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
        # Remove from running_tasks SYNCHRONOUSLY before any further awaits.
        # This closes the race window where the frontend safety-timeout fires
        # cancel_query after natural completion.
        _running_tasks.pop(thread_id, None)

        # Atomically claim ownership of the done transition.  Using WHERE
        # status='running' means only one writer (runner or cancel endpoint)
        # can commit and emit done — whoever commits second touches 0 rows
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
                    await emit_done(thread_id, "failed", str(exc))
        except Exception as cleanup_exc:
            logger.warning(
                "[graph_runner] cleanup error thread_id=%s: %s",
                thread_id,
                cleanup_exc,
            )
        await cleanup_thread_session(thread_id)
