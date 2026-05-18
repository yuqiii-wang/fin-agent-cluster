"""backend.users.queries._helpers — Shared row converters and cascade helpers."""

from __future__ import annotations

import logging
from typing import Any

from backend.db.postgres import raw_conn
from backend.users.schemas import NodeExecutionInfo, QueryResponse
from backend.users.queries._sql import _ACTIVE_SIBLING_NODE_COUNT, _ACTIVE_TOP_LEVEL_NODE_COUNT

logger = logging.getLogger(__name__)


def _row_to_query_response(row: Any) -> QueryResponse:
    """Convert a DB row (tuple or mapping) to :class:`QueryResponse`."""
    return QueryResponse(
        thread_id=row["thread_id"],
        status=row["status"],
        query=row["query"],
        answer=row["answer"],
        error=row["error"],
        created_at=row["created_at"],
        completed_at=row["completed_at"],
    )


def _row_to_node_info(r: Any) -> NodeExecutionInfo:
    """Convert a DB row (mapping) to :class:`NodeExecutionInfo`."""
    return NodeExecutionInfo(
        node_id=r["node_id"],
        thread_id=r["thread_id"],
        node_name=r["node_name"],
        status=r["status"],
        type=r["type"],
        parent_node_id=r["parent_node_id"],
        parallel_group=r["parallel_group"],
        version=r["version"] or 0,
        checkpoint_id=r["checkpoint_id"] or "",
        prev_node_ids=r["prev_node_ids"] or [],
        next_node_ids=r["next_node_ids"] or [],
        task_ids=r["task_ids"] or [],
        is_forked=bool(r["is_forked"]),
        forked_from_version=r["forked_from_version"],
        view_type=r["view_type"] or "Json",
        view_schema=r["view_schema"] or {},
        stats_views=list(r["stats_views"]) if r["stats_views"] else [],
        input=r["input"],
        output=r["output"],
        started_at=r["started_at"],
        elapsed_ms=r["elapsed_ms"] or 0,
        updated_at=r["updated_at"],
    )


def _get_topology_safe() -> "GraphTopologyResponse | None":
    """Return the compiled graph topology, or None if the graph is not yet ready."""
    try:
        from backend.api.graph.topology import get_compiled_topology, GraphTopologyResponse  # noqa: F401
        return get_compiled_topology()
    except Exception:
        return None


async def _cascade_up_from_cancelled_node(
    thread_id: str,
    node_id: str,
    parent_node_id: str | None,
    reason: str,
) -> None:
    """Propagate cancellation upward after a node reaches 'cancelled' state.

    Rules (applied once per level, non-recursive for top-level):
    - Inner node (``parent_node_id`` set): if no active siblings remain inside
      the parent subgraph, cancel the parent subgraph node and recurse.
    - Top-level node (``parent_node_id`` is ``None``): if no active top-level
      nodes remain, cancel the thread (sets Redis cancel flag + DB status).

    Args:
        thread_id:      LangGraph thread UUID.
        node_id:        The node that was just cancelled.
        parent_node_id: Parent subgraph node ID, or ``None`` for top-level nodes.
        reason:         Propagated cancellation reason label.
    """
    from backend.langgraph.lifecycle.threads.nodes import cancel_node as _cancel_node_lc
    from backend.langgraph.lifecycle import cancel_thread as _cancel_thread_lc
    from backend.main_thread.cancel_flag import set_cancel_flag

    if parent_node_id:
        try:
            async with raw_conn(readonly=True) as conn:
                cur = await conn.execute(
                    _ACTIVE_SIBLING_NODE_COUNT,
                    (parent_node_id, thread_id),
                )
                row = await cur.fetchone()
            active_siblings = row["cnt"] if row else 0
        except Exception as exc:
            logger.error(
                "[cascade_up] DB error checking siblings parent_node_id=%s: %s",
                parent_node_id, exc,
            )
            return

        if active_siblings > 0:
            return

        try:
            async with raw_conn(readonly=True) as conn:
                cur = await conn.execute(
                    "SELECT parent_node_id FROM fin_agents.nodes"
                    " WHERE node_id = %s AND thread_id = %s",
                    (parent_node_id, thread_id),
                )
                prow = await cur.fetchone()
            grandparent_id: str | None = prow["parent_node_id"] if prow else None
        except Exception as exc:
            logger.error(
                "[cascade_up] DB error fetching parent info node_id=%s: %s",
                parent_node_id, exc,
            )
            return

        await _cancel_node_lc(thread_id, parent_node_id, reason=reason)
        await _cascade_up_from_cancelled_node(
            thread_id, parent_node_id, grandparent_id, reason
        )
        return

    try:
        async with raw_conn(readonly=True) as conn:
            cur = await conn.execute(
                _ACTIVE_TOP_LEVEL_NODE_COUNT,
                (thread_id,),
            )
            row = await cur.fetchone()
        active_top_nodes = row["cnt"] if row else 0
    except Exception as exc:
        logger.error(
            "[cascade_up] DB error checking top-level nodes thread_id=%s: %s",
            thread_id, exc,
        )
        return

    if active_top_nodes > 0:
        return

    try:
        await set_cancel_flag(thread_id)
        await _cancel_thread_lc(thread_id, reason=reason)
    except Exception as exc:
        logger.error(
            "[cascade_up] thread cancel failed thread_id=%s: %s",
            thread_id, exc,
        )


__all__ = [
    "_row_to_query_response",
    "_row_to_node_info",
    "_get_topology_safe",
    "_cascade_up_from_cancelled_node",
]
