"""Service logic for ACKing a received query and starting graph execution."""

from __future__ import annotations

import asyncio
import logging

from fastapi import HTTPException
from sqlalchemy import select

from backend.api.errors import API_QUERY_NOT_FOUND, API_QUERY_STATUS_CONFLICT
from backend.api.registry import mark_task_active
from backend.api.registry import running_tasks as _running_tasks
from backend.db import get_session_factory as _get_session_factory
from backend.db.redis.streams.publisher import ack_pending_notify
from backend.graph.runner import run_graph_async
from backend.sse_notifications.query_lifecycle import emit_query_ack_confirmed
from backend.users.models import UserQuery
from backend.users.schemas import QueryResponse

logger = logging.getLogger(__name__)


async def ack_query(thread_id: str) -> QueryResponse:
    """ACK a received query and launch LangGraph execution.

    Uses a ``SELECT … FOR UPDATE`` row-level lock so concurrent duplicate ACK
    requests cannot start the graph more than once.  Idempotent — if the query
    is already ``running`` re-emits ``query_ack_confirmed`` so the client stops
    retrying.

    Args:
        thread_id: LangGraph thread UUID returned by ``POST /query``.

    Returns:
        ``QueryResponse`` with ``status='running'``.

    Raises:
        404: Thread not found.
        409: Query is not in a state that allows ACK.
    """
    factory = _get_session_factory()

    async with factory() as session:
        uq = await session.scalar(
            select(UserQuery)
            .where(UserQuery.thread_id == thread_id)
            .with_for_update()
        )
        if uq is None:
            raise HTTPException(
                status_code=404,
                detail={"code": API_QUERY_NOT_FOUND, "message": "Query not found"},
            )

        if uq.status == "running" and uq.is_ack:
            # Idempotent: already acked and started — just resend confirmation.
            await emit_query_ack_confirmed(thread_id)
            return QueryResponse(thread_id=thread_id, status="running")

        if uq.status != "received":
            raise HTTPException(
                status_code=409,
                detail={
                    "code": API_QUERY_STATUS_CONFLICT,
                    "message": f"Cannot ack query with status '{uq.status}'",
                },
            )

        perf_params: dict = uq.extra.get("perf_params", {})
        query_text: str = uq.query

        uq.status = "running"
        uq.is_ack = True
        await session.commit()

    # Ack the pending query_received notify so the drain cycle stops retrying.
    await ack_pending_notify(thread_id, "query_received", None)

    # Schedule graph execution as a non-blocking asyncio.Task.
    task = asyncio.create_task(
        run_graph_async(
            thread_id,
            query_text,
            perf_total_tokens=perf_params.get("perf_total_tokens", 100_000),
            perf_timeout_secs=perf_params.get("perf_timeout_secs", 20),
            perf_test_mode=perf_params.get("perf_test_mode", "throughput"),
            perf_token_per_sec=perf_params.get("perf_token_per_sec", 500),
        ),
        name=f"graph:{thread_id}",
    )
    _running_tasks[thread_id] = task
    await mark_task_active(thread_id)

    # Confirm to the client that execution has started.
    await emit_query_ack_confirmed(thread_id)

    logger.info("[ack] query_ack_confirmed thread_id=%s", thread_id)
    return QueryResponse(thread_id=thread_id, status="running")
