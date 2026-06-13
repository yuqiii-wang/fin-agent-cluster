"""complete_node and its internal implementation."""

from __future__ import annotations

import json
import logging
import time
from typing import Any

from backend.db.postgres import raw_conn
from backend.langgraph.lifecycle.errors import LIFECYCLE_DB_ERROR
from backend.langgraph.lifecycle.threads.nodes.sql import (
    _UPDATE_NODE_COMPLETED,
    _UPDATE_NODE_EXECUTION_OUTPUT,
    _UPDATE_NODE_NEXT_IDS,
)
from backend.langgraph.lifecycle.threads.nodes.sse import emit_node_sse

logger = logging.getLogger(__name__)


async def _complete_node_internal(
    thread_id: str,
    node_id: str,
    node_name: str,
    output_data: dict[str, Any] | None,
    failed: bool,
    error: str | None,
    next_node_ids: list[str] | None,
) -> None:
    """Internal implementation used by both ``complete_node`` and auto-complete."""
    from backend.main_thread.context import get_fencing_token
    fencing_token = get_fencing_token()

    t0 = time.monotonic()
    status = "failed" if failed else "completed"
    out: dict[str, Any]
    if failed:
        out = {"error": error or "unknown error"}
    else:
        out = output_data or {}

    async with raw_conn() as conn:
        cur = await conn.execute(
            _UPDATE_NODE_COMPLETED,
            (status, node_id, thread_id, fencing_token),
        )
        updated = cur.rowcount
        if updated > 0:
            await conn.execute(
                _UPDATE_NODE_EXECUTION_OUTPUT,
                (json.dumps(out), node_id),
            )
            if next_node_ids:
                await conn.execute(
                    _UPDATE_NODE_NEXT_IDS,
                    (next_node_ids, node_id, thread_id),
                )

    if updated == 0:
        try:
            async with raw_conn(readonly=True) as _rc:
                _cur = await _rc.execute(
                    "SELECT status FROM fin_agents.nodes WHERE node_id = %s AND thread_id = %s",
                    (node_id, thread_id),
                )
                _row = await _cur.fetchone()
            _existing = _row["status"] if _row else "not_found"
        except Exception:
            _existing = "unknown"
        logger.debug(
            "[lifecycle:node] %s skipped node_id=%s node_name=%s existing_status=%s -- node already terminal",
            status, node_id, node_name, _existing,
        )
        return  # Already terminal -- skip SSE.

    logger.debug(
        "[lifecycle:node] %s node_id=%s node_name=%s db_ms=%.0f -- emitting SSE",
        status, node_id, node_name, (time.monotonic() - t0) * 1000,
    )
    t_sse = time.monotonic()
    await emit_node_sse(
        thread_id, node_id, node_name,
        status=status,
        payload={"output": out},
    )
    logger.debug(
        "[lifecycle:node] %s SSE done node_id=%s node_name=%s sse_ms=%.0f total_ms=%.0f",
        status, node_id, node_name,
        (time.monotonic() - t_sse) * 1000, (time.monotonic() - t0) * 1000,
    )


async def complete_node(
    thread_id: str,
    node_id: str,
    node_name: str,
    output_data: dict[str, Any] | None = None,
    *,
    failed: bool = False,
    error: str | None = None,
    next_node_ids: list[str] | None = None,
) -> None:
    """Mark a node as completed (or failed) and emit the SSE event.

    Writes execution output to ``fin_agents.node_executions`` and updates
    topology (next_node_ids) on ``fin_agents.nodes``.

    Idempotent: if the node is already terminal, the UPDATE is a no-op
    and no SSE is emitted.

    Args:
        thread_id:     LangGraph thread UUID.
        node_id:       Node ID to update.
        node_name:     Human-readable node name.
        output_data:   Result payload (written to ``node_executions``).
        failed:        ``True`` to mark as failed.
        error:         Error message included in output when *failed*.
        next_node_ids: Successor node IDs to record in the nodes table.
    """
    await _complete_node_internal(
        thread_id=thread_id,
        node_id=node_id,
        node_name=node_name,
        output_data=output_data,
        failed=failed,
        error=error,
        next_node_ids=next_node_ids,
    )


__all__ = ["complete_node"]
