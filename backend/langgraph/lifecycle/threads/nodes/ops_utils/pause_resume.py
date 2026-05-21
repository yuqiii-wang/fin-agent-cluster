"""pause_node and resume_node lifecycle transitions."""

from __future__ import annotations

import logging

from backend.db.postgres import raw_conn
from backend.langgraph.lifecycle.threads.nodes.sql import (
    _PAUSE_NODE,
    _RESUME_NODE,
)
from backend.langgraph.lifecycle.threads.nodes.sse import emit_node_sse

logger = logging.getLogger(__name__)


async def pause_node(
    thread_id: str,
    node_id: str,
    node_name: str,
    *,
    is_last_paused_by_server: bool,
) -> bool:
    """Mark a node as paused and emit a ``node_status: pause`` SSE event.

    Called when a ``TaskPausedError`` is caught by the node's ``__call__``
    method.  Sets ``is_last_paused_by_server`` to distinguish server-initiated
    pauses (auto-resumed on restart) from user-initiated pauses (require
    explicit Continue action).

    Only transitions nodes that are currently ``'running'`` — idempotent if
    the node is already paused or terminal.

    Args:
        thread_id:               LangGraph thread UUID.
        node_id:                 Node UUID.
        node_name:               Human-readable node name.
        is_last_paused_by_server: ``True`` when the server shutdown caused
            the pause; ``False`` when the user clicked Pause.

    Returns:
        ``True`` if the node was updated; ``False`` if already terminal / no-op.
    """
    from backend.main_thread.context import get_fencing_token
    fencing_token = get_fencing_token()

    async with raw_conn() as conn:
        cur = await conn.execute(
            _PAUSE_NODE, (is_last_paused_by_server, node_id, thread_id, fencing_token)
        )
        rows = await cur.fetchall()

    if not rows:
        return False

    await emit_node_sse(
        thread_id, node_id, node_name,
        status="paused",
        payload={"is_last_paused_by_server": is_last_paused_by_server},
    )
    return True


async def resume_node(
    thread_id: str,
    node_id: str,
    node_name: str,
) -> bool:
    """Reset a paused node back to running when the user continues its task.

    Called by :func:`~backend.users.queries.retry.retry_task` when the user
    clicks Continue on a paused task.  Transitions the node from ``'paused'``
    to ``'running'`` and emits a ``node_status: running`` SSE event.

    No fencing-token guard because this is called from the API layer outside
    any active graph run.

    Args:
        thread_id: LangGraph thread UUID.
        node_id:   Node UUID.
        node_name: Human-readable node name.

    Returns:
        ``True`` if the node was updated; ``False`` if already running or terminal.
    """
    async with raw_conn() as conn:
        cur = await conn.execute(_RESUME_NODE, (node_id, thread_id))
        rows = await cur.fetchall()

    if not rows:
        return False

    await emit_node_sse(thread_id, node_id, node_name, status="running", payload={})
    return True


__all__ = ["pause_node", "resume_node"]
