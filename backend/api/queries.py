"""FastAPI router for user query endpoints.

Mounted at ``/users`` under the parent API router, so full paths are:

    POST /api/v1/users/query
    POST /api/v1/users/query/{thread_id}/ack
    POST /api/v1/users/query/{thread_id}/cancel
    GET  /api/v1/users/query/{thread_id}
    GET  /api/v1/users/query/{thread_id}/tasks
    GET  /api/v1/users/query/{thread_id}/nodes

Query handshake flow
--------------------
1. ``POST /query`` — creates a ``user_queries`` row with ``status='received'``,
   fires ``query_received`` via pg_notify (+ pending-notify store for retry),
   and returns ``{thread_id, status='received'}``.  The graph is **not** started.

2. Client subscribes to ``GET /stream/{thread_id}`` and waits for the
   ``query_received`` SSE event.

3. Client posts ``POST /query/{thread_id}/ack`` to acknowledge receipt.
   The backend sets ``is_ack=True``, flips status to ``'running'``, starts
   the LangGraph asyncio.Task, and emits ``query_ack_confirmed`` via SSE.

4. Client receives ``query_ack_confirmed`` and stops sending ACK retries.

Duplicate-submission guard
--------------------------
If the same ``user_id`` submits the same ``query`` text while an existing row
is still in ``received/pending/running`` state and was created within the last
60 seconds, the backend returns a NACK with ``status='cancelled'`` and the
existing ``thread_id`` so the client can re-attach to the live SSE stream.
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from datetime import datetime, timedelta, timezone

from typing import Annotated

from fastapi import APIRouter, Header, HTTPException
from sqlalchemy import and_, select, update
from sqlalchemy.exc import IntegrityError

from backend.db import get_session_factory as _get_session_factory
from backend.db.redis.publisher import ack_pending_notify
from backend.db.redis.cancel_signal import publish_cancel
from backend.db.redis.query_phase import delete_query_phase, set_query_phase
from backend.graph.models import AgentTask, NodeExecution
from backend.api.registry import running_tasks as _running_tasks, mark_task_active
from backend.sse_notifications import emit_done
from backend.sse_notifications.query_lifecycle import emit_query_ack_confirmed, emit_query_received, emit_query_status
from backend.graph.runner import run_graph_async
from backend.users.auth import ensure_guest
from backend.users.models import UserQuery
from backend.users.schemas import QueryRequest, QueryResponse, SessionStatus, TaskInfo, NodeExecutionInfo

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/users", tags=["users"])

#: Active statuses — a query with one of these is still being processed.
_ACTIVE_STATUSES: tuple[str, ...] = ("received", "pending", "running")

#: Dedup window in seconds — duplicate submissions within this window are rejected.
_DEDUP_WINDOW_SECS: int = 60


@router.post("/query", response_model=QueryResponse)
async def run_query(
    request: QueryRequest,
    x_user_token: Annotated[str, Header(alias="X-User-Token")],
) -> QueryResponse:
    """Accept a financial analysis query and await client ACK before processing.

    Creates a ``user_queries`` row with ``status='received'``, fires a
    ``query_received`` pg_notify event (with pending-notify retry), and returns
    ``{thread_id, status='received'}``.  The LangGraph execution is **not**
    started until the client ACKs via ``POST /query/{thread_id}/ack``.

    Duplicate submissions from the same user for the same query text within
    :data:`_DEDUP_WINDOW_SECS` are rejected with ``status='cancelled'`` and
    the existing ``thread_id`` so the client can re-attach.

    Args:
        request:      Query payload with the user's natural-language question.
        x_user_token: Guest bearer token from ``X-User-Token`` header.

    Returns:
        ``QueryResponse`` with *thread_id* and ``status='received'`` on
        success, or ``status='cancelled'`` (NACK) for duplicate submissions.
    """
    user, _ = await ensure_guest(x_user_token)
    factory = _get_session_factory()

    async with factory() as session:
        # ── Dedup guard ────────────────────────────────────────────────────
        cutoff = datetime.now(timezone.utc) - timedelta(seconds=_DEDUP_WINDOW_SECS)
        existing = await session.scalar(
            select(UserQuery)
            .where(
                and_(
                    UserQuery.user_id == user.id,
                    UserQuery.query == request.query,
                    UserQuery.status.in_(list(_ACTIVE_STATUSES)),
                    UserQuery.created_at >= cutoff,
                )
            )
            .order_by(UserQuery.created_at.desc())
            .limit(1)
        )
        if existing:
            logger.info(
                "[queries] dedup_nack thread_id=%s user=%s",
                existing.thread_id,
                user.id,
            )
            return QueryResponse(
                thread_id=existing.thread_id,
                status="cancelled",
                error="duplicate_query",
            )

        # ── Persist new query with status='received' ────────────────────────
        thread_id = str(uuid.uuid4())
        session.add(
            UserQuery(
                thread_id=thread_id,
                user_id=user.id,
                query=request.query,
                status="received",
                extra={
                                    "perf_params": {
                        "perf_total_tokens": request.perf_total_tokens or 100_000,
                        "perf_timeout_secs": request.perf_timeout_secs or 60,
                        "perf_test_mode": request.perf_test_mode or "throughput",
                        "perf_token_per_sec": request.perf_token_per_sec or 500,
                    }
                },
            )
        )
        try:
            await session.commit()
        except IntegrityError:
            # Concurrent duplicate INSERT from another instance hit the unique index.
            await session.rollback()
            async with factory() as s2:
                dup = await s2.scalar(
                    select(UserQuery)
                    .where(
                        and_(
                            UserQuery.user_id == user.id,
                            UserQuery.query == request.query,
                            UserQuery.status.in_(list(_ACTIVE_STATUSES)),
                        )
                    )
                    .order_by(UserQuery.created_at.desc())
                    .limit(1)
                )
            if dup:
                logger.info(
                    "[queries] dedup_nack_concurrent thread_id=%s user=%s",
                    dup.thread_id, user.id,
                )
                return QueryResponse(
                    thread_id=dup.thread_id,
                    status="cancelled",
                    error="duplicate_query",
                )
            raise

    logger.info(
        "[queries] query_received thread_id=%s query=%r",
        thread_id,
        request.query[:80],
    )

    # Store phase in Redis so late-connecting SSE clients can replay it.
    await set_query_phase(thread_id, "received")
    # Emit query_status for the existing query_status replay channel.
    await emit_query_status(thread_id, "received")
    # Emit query_received via pg_notify + push to pending-notify store for retry.
    await emit_query_received(thread_id)

    return QueryResponse(thread_id=thread_id, status="received")


@router.post("/query/{thread_id}/ack", response_model=QueryResponse)
async def ack_query(
    thread_id: str,
    x_user_token: Annotated[str, Header(alias="X-User-Token")],
) -> QueryResponse:
    """Acknowledge a received query, starting LangGraph execution.

    Must be called by the client after receiving the ``query_received`` SSE
    event.  This endpoint is idempotent — if the query is already in
    ``running`` state (prior ACK succeeded), it re-emits ``query_ack_confirmed``
    so the client stops retrying.

    Uses a ``SELECT … FOR UPDATE`` row-level lock so concurrent duplicate ACK
    requests cannot start the graph more than once.

    Args:
        thread_id:    LangGraph thread UUID returned by ``POST /query``.
        x_user_token: Guest bearer token (used for auth validation only).

    Returns:
        ``QueryResponse`` with ``status='running'``.

    Raises:
        404: Thread not found.
        409: Query is not in a state that allows ACK
             (e.g. already completed, failed, or cancelled).
    """
    await ensure_guest(x_user_token)
    factory = _get_session_factory()

    async with factory() as session:
        uq = await session.scalar(
            select(UserQuery)
            .where(UserQuery.thread_id == thread_id)
            .with_for_update()
        )
        if uq is None:
            raise HTTPException(status_code=404, detail="Query not found")

        if uq.status == "running" and uq.is_ack:
            # Idempotent: already acked and started — just resend confirmation.
            await emit_query_ack_confirmed(thread_id)
            return QueryResponse(thread_id=thread_id, status="running")

        if uq.status != "received":
            raise HTTPException(
                status_code=409,
                detail=f"Cannot ack query with status '{uq.status}'",
            )

        perf_params: dict = uq.extra.get("perf_params", {})
        query_text: str = uq.query

        uq.status = "running"
        uq.is_ack = True
        uq.ack_at = datetime.now(timezone.utc)
        await session.commit()

    # Ack the pending query_received notify so the drain cycle stops retrying.
    await ack_pending_notify(thread_id, "query_received", None)

    # Schedule graph execution as a non-blocking asyncio.Task.
    task = asyncio.create_task(
                run_graph_async(
            thread_id,
            query_text,
            perf_total_tokens=perf_params.get("perf_total_tokens", 100_000),
            perf_timeout_secs=perf_params.get("perf_timeout_secs", 60),
            perf_test_mode=perf_params.get("perf_test_mode", "throughput"),
            perf_token_per_sec=perf_params.get("perf_token_per_sec", 500),
        ),
        name=f"graph:{thread_id}",
    )
    _running_tasks[thread_id] = task
    await mark_task_active(thread_id)

    # Confirm to the client that execution has started.
    await emit_query_ack_confirmed(thread_id)

    return QueryResponse(thread_id=thread_id, status="running")


@router.post("/query/{thread_id}/cancel", response_model=QueryResponse)
async def cancel_query(
    thread_id: str,
    reason: str = "user",
) -> QueryResponse:
    """Cancel a running query.

    Revokes the Celery task running the graph worker.  The cancel endpoint
    also takes ownership of the final DB status update and ``done`` SSE event
    so the graph runner does not have to.

    Args:
        thread_id: The UUID returned when the query was submitted.
        reason:    Why the query is being cancelled.  ``"user"`` (default) for
                   an explicit user action; ``"timeout"`` when the client-side
                   safety timeout fired before all tokens were published.  The
                   value is forwarded verbatim in the ``done`` SSE event so the
                   frontend can distinguish the two cases without applying any
                   local status override.

    Returns:
        ``QueryResponse`` with ``status`` matching *reason*.
    """
    # Pop the local asyncio.Task — may be None if this instance does not own the query.
    local_task = _running_tasks.pop(thread_id, None)

    # Guard: if the local task already finished naturally the runner claimed the
    # done transition; return early to avoid a duplicate done event.
    if local_task is not None and local_task.done():
        logger.info(
            "[queries] cancel_skipped_already_done thread_id=%s reason=%s",
            thread_id, reason,
        )
        return QueryResponse(thread_id=thread_id, status="completed")

    done_status = reason if reason == "timeout" else "cancelled"
    db_status = "cancelled"

    # Atomically claim the cancel transition.  WHERE status IN ('running', 'received')
    # ensures only one writer (this endpoint or the graph runner) emits done.
    # Works correctly on any instance — the DB is the source of truth.
    factory = _get_session_factory()
    async with factory() as session:
        result_update = await session.execute(
            update(UserQuery)
            .where(
                UserQuery.thread_id == thread_id,
                UserQuery.status.in_(["running", "received"]),
            )
            .values(status=db_status)
            .returning(UserQuery.thread_id)
        )
        claimed = result_update.fetchone() is not None
        if claimed:
            await session.execute(
                update(AgentTask)
                .where(AgentTask.thread_id == thread_id, AgentTask.status == "running")
                .values(status=db_status)
            )
        await session.commit()

    if claimed:
        await emit_done(thread_id, done_status, "Query cancelled by user")
        await delete_query_phase(thread_id)

    # Publish Redis cancel signal so the owning instance cancels its asyncio.Task.
    await publish_cancel(thread_id, reason)

    # Cancel local task if this instance owns it (no-op when task is on another instance).
    if local_task is not None and not local_task.done():
        local_task.cancel()

    logger.info(
        "[queries] task_cancelled thread_id=%s reason=%s claimed=%s",
        thread_id, reason, claimed,
    )
    return QueryResponse(thread_id=thread_id, status=done_status)


@router.get("/query/{thread_id}", response_model=QueryResponse)
async def get_query_status(thread_id: str) -> QueryResponse:
    """Get the status of a previously submitted query.

    Args:
        thread_id: The UUID returned when the query was submitted.

    Returns:
        ``QueryResponse`` reflecting the current *status* and any *error*.
    """
    factory = _get_session_factory()
    async with factory() as session:
        result = await session.execute(
            select(UserQuery).where(UserQuery.thread_id == thread_id)
        )
        row = result.scalar_one_or_none()

    if not row:
        raise HTTPException(status_code=404, detail="Query not found")

    return QueryResponse(
        thread_id=row.thread_id,
        status=row.status,
        report=row.answer,
        error=row.error,
    )


@router.get("/query/{thread_id}/tasks", response_model=SessionStatus)
async def get_query_tasks(thread_id: str) -> SessionStatus:
    """Return the query record and all its agent sub-tasks.

    Used by clients to discover active task IDs, node names, and statuses so
    they can correlate streaming events (received via the SSE endpoint) back
    to specific work items.

    Args:
        thread_id: The UUID returned when the query was submitted.

    Returns:
        ``SessionStatus`` containing the query status and a list of
        ``TaskInfo`` records — one per sub-task across all nodes.
    """
    factory = _get_session_factory()
    async with factory() as session:
        uq_result = await session.execute(
            select(UserQuery).where(UserQuery.thread_id == thread_id)
        )
        uq_row = uq_result.scalar_one_or_none()
        if not uq_row:
            raise HTTPException(status_code=404, detail="Query not found")

        tasks_result = await session.execute(
            select(AgentTask)
            .where(AgentTask.thread_id == thread_id)
            .order_by(AgentTask.created_at)
        )
        task_rows = tasks_result.scalars().all()

    return SessionStatus(
        thread_id=thread_id,
        user_query_id=uq_row.id,
        status=uq_row.status,
        tasks=[
            TaskInfo(
                id=t.id,
                thread_id=t.thread_id,
                node_execution_id=t.node_execution_id,
                node_name=t.node_name,
                task_key=t.task_key,
                status=t.status,
                input=t.input,
                output=t.output,
                created_at=t.created_at,
                updated_at=t.updated_at,
            )
            for t in task_rows
        ],
    )


@router.get("/query/{thread_id}/nodes", response_model=list[NodeExecutionInfo])
async def get_node_executions(thread_id: str) -> list[NodeExecutionInfo]:
    """Return node-level input/output snapshots for a thread.

    Each entry corresponds to one node invocation and contains the full
    ``input`` state fed into the node and the ``output`` state diff it
    returned.  Used by the UI to show per-node I/O in the pipeline graph.

    Args:
        thread_id: The UUID returned when the query was submitted.

    Returns:
        List of :class:`NodeExecutionInfo` ordered by execution start time.
    """
    factory = _get_session_factory()
    async with factory() as session:
        result = await session.execute(
            select(NodeExecution)
            .where(NodeExecution.thread_id == thread_id)
            .order_by(NodeExecution.started_at)
        )
        rows = result.scalars().all()

    return [
        NodeExecutionInfo(
            id=r.id,
            node_name=r.node_name,
            input=r.input,
            output=r.output,
            started_at=r.started_at,
            elapsed_ms=r.elapsed_ms,
        )
        for r in rows
    ]
