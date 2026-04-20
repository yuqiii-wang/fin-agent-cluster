"""Graph runner — Celery task and async execution of the unified LangGraph workflow.

Architecture
------------
Each query is dispatched to a **dedicated per-thread Celery queue** so that
no two queries share a worker slot and there is no head-of-line blocking:

    POST /api/v1/users/query
      └─ queries.py
           └─ celery_app.control.add_consumer("graph:<thread_id>")
           └─ run_graph_task.apply_async(queue="graph:<thread_id>")
                └─ Celery worker (isolated per-thread queue)
                     └─ asyncio.run(run_graph_async(...))
                          └─ graph.ainvoke(...)
                               └─ LangGraph nodes
                                    └─ LLM chain.astream()  →  stream_token() XADD
                                         └─ Redis Stream tokens:<thread_id>
                                              └─ SSE generator XREAD BLOCK (independent)

Token flow
----------
LangGraph nodes write tokens to ``tokens:<thread_id>`` via ``stream_token()``
(XADD) directly inside the asyncio coroutine running in the Celery worker.
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
The cancel endpoint calls ``celery_app.control.revoke(task_id, terminate=True)``
on the Celery result stored in ``running_tasks``.  The cancel endpoint also
updates the DB and emits ``done`` so the runner does not have to handle those.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime

from celery.utils.log import get_task_logger
from sqlalchemy import select, update

from backend.db import checkpointer, get_session_factory as _get_session_factory
from backend.db.redis.query_phase import delete_query_phase, set_query_phase
from backend.graph.builder import build_unified_graph
from backend.sse_notifications import emit_done
from backend.sse_notifications.perf_test import emit_query_status
from backend.streaming.celery_app import celery_app
from backend.users.models import UserQuery

logger = logging.getLogger(__name__)
task_logger = get_task_logger(__name__)

# ---------------------------------------------------------------------------
# Celery task — one per query, isolated per-thread queue
# ---------------------------------------------------------------------------

#: Fully-qualified task name used by both the decorator and ``send_task``.
TASK_NAME = "backend.graph.runner.run_graph_task"


@celery_app.task(
    name=TASK_NAME,
    bind=True,
    max_retries=0,      # LLM inference is not idempotent — never auto-retry
    ignore_result=False,
    acks_late=True,     # ACK only after completion so a worker crash re-queues the task
)
def run_graph_task(
    self,  # type: ignore[misc]
    thread_id: str,
    query: str,
    perf_total_tokens: int = 100_000,
    perf_timeout_secs: int = 60,
    perf_pub_mode: str = "browser",
) -> None:
    """Celery task: run the unified LangGraph workflow for one query.

    Wraps :func:`run_graph_async` in ``asyncio.run()`` so the full async
    LangGraph graph — including LLM ``astream()`` calls — executes inside
    a Celery worker process.  Each invocation creates and tears down its own
    event loop, giving complete isolation between concurrent queries.

    Args:
        thread_id:         LangGraph UUID already persisted to the DB.
        query:             Raw user query string.
        perf_total_tokens: Tokens per stream (perf-test only).
        perf_timeout_secs: Hard deadline in seconds (perf-test only).
        perf_pub_mode:     ``"browser"`` or ``"locust"`` (perf-test only).
    """
    task_logger.info(
        "[graph_runner] task_start thread_id=%s query=%r",
        thread_id,
        query[:80],
    )
    asyncio.run(
        run_graph_async(
            thread_id,
            query,
            perf_total_tokens=perf_total_tokens,
            perf_timeout_secs=perf_timeout_secs,
            perf_pub_mode=perf_pub_mode,
        )
    )
    task_logger.info("[graph_runner] task_done thread_id=%s", thread_id)


# ---------------------------------------------------------------------------
# Async implementation
# ---------------------------------------------------------------------------


async def run_graph_async(
    thread_id: str,
    query: str,
    perf_total_tokens: int = 100_000,
    perf_timeout_secs: int = 60,
    perf_pub_mode: str = "browser",
) -> None:
    """Run the unified LangGraph workflow for one query.

    Routes to the fin-analysis pipeline or the perf-test node based on
    ``query``.  Called by :func:`run_graph_task` inside the Celery worker's
    ``asyncio.run()`` context.

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
        perf_total_tokens:   Tokens per stream (perf-test only).
        perf_timeout_secs:   Hard deadline in seconds (perf-test only).
        perf_pub_mode:       ``"browser"`` — emit perf_token SSE events;
                             ``"locust"`` — write to locust digest Redis key instead.
    """
    factory = _get_session_factory()
    try:
        # Transition phase from "received" to "preparing" as soon as the
        # Celery worker picks up the task.  This signals to the frontend that
        # the request was not lost in the queue.
        await set_query_phase(thread_id, "preparing")
        await emit_query_status(thread_id, "preparing")

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
                # Perf-test fields — used only when query == PERF_TEST_TRIGGER.
                "total_tokens": perf_total_tokens,
                "timeout_secs": perf_timeout_secs,
                "pub_mode": perf_pub_mode,
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

        await delete_query_phase(thread_id)
        logger.info("[graph_runner] completed thread_id=%s", thread_id)

    except asyncio.CancelledError:
        # Cancel endpoint has already updated DB + emitted done; nothing to do.
        await delete_query_phase(thread_id)
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
        await delete_query_phase(thread_id)
