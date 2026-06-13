"""backend.users.queries.submit -- submit_query handler."""

from __future__ import annotations

import uuid
from typing import Any

from backend.db.postgres import raw_conn
from backend.users.schemas import QueryResponse, SseInfo
from backend.users.queries._sql import _INSERT_QUERY_IMMEDIATE
from backend.users.queries._helpers import _get_topology_safe


async def submit_query(request: "QueryRequest", user: Any) -> QueryResponse:  # type: ignore[name-defined]
    """Insert a new user query, immediately start graph execution, and return SSE bootstrap info.

    Creates a row in ``fin_agents.user_queries`` with ``status='received'`` and
    ``is_ack=TRUE``, dispatches the LangGraph run as a background asyncio task.
    Status transitions to ``'running'`` once the graph task begins executing.
    Returns Centrifugo SSE connection details so the client can subscribe to
    ``thread:{thread_id}`` on the correct shard without a separate ACK round-trip.

    Args:
        request: Incoming query payload.
        user:    Authenticated guest user object (must have ``id`` attribute).

    Returns:
        :class:`QueryResponse` with ``status='received'``, the new ``thread_id``,
        and an :class:`SseInfo` block for the matching centrifugo-sse shard.
    """
    from backend.auth.jwt import make_connection_token, make_subscription_token
    from backend.centrifugo_mq.client import get_shard_index, get_sse_shard_index
    from backend.config import get_settings
    from fastapi import HTTPException
    from psycopg.errors import UniqueViolation
    from backend.api.errors import API_ERRORS, API_QUERY_DUPLICATE
    from backend.users.schemas import QueryRequest  # noqa: F401

    settings = get_settings()
    thread_id = str(uuid.uuid4())

    try:
        async with raw_conn() as conn:
            cur = await conn.execute(
                _INSERT_QUERY_IMMEDIATE,
                (thread_id, str(user.id), request.query),
            )
            row = await cur.fetchone()
    except UniqueViolation:
        raise HTTPException(
            status_code=429,
            detail={"code": API_QUERY_DUPLICATE, "message": API_ERRORS[API_QUERY_DUPLICATE]},
        )

    from backend.db.redis.session.thread_user_store import set_thread_user
    from backend.db.redis.session.viewer_store import set_viewer
    await set_thread_user(thread_id, str(user.id))
    await set_viewer(str(user.id), thread_id)

    from backend.main_thread import dispatch_graph_run
    await dispatch_graph_run(thread_id, request.query)

    user_id = str(user.id)
    secret = settings.CENTRIFUGO_SECRET

    sse_shard = get_sse_shard_index(thread_id)
    channel = f"thread:{thread_id}"
    ws_url_sse = f"{settings.CENTRIFUGO_PUBLIC_BASE}/centrifugo-sse-{sse_shard}/connection/websocket"

    llm_shard = get_shard_index(thread_id)
    ws_url_llm = f"{settings.CENTRIFUGO_PUBLIC_BASE}/centrifugo-llm-{llm_shard}/connection/websocket"

    return QueryResponse(
        thread_id=row["thread_id"],
        status=row["status"],
        query=row["query"],
        answer=None,
        error=None,
        created_at=row["created_at"],
        completed_at=row["completed_at"],
        sse=SseInfo(
            ws_url=ws_url_sse,
            connection_token=make_connection_token(user_id, secret),
            subscription_token=make_subscription_token(user_id, channel, secret),
            channel=channel,
        ),
        llm=SseInfo(
            ws_url=ws_url_llm,
            connection_token=make_connection_token(user_id, secret),
            subscription_token=make_subscription_token(user_id, channel, secret),
            channel=channel,
        ),
        topology=_get_topology_safe(),
    )


__all__ = ["submit_query"]
