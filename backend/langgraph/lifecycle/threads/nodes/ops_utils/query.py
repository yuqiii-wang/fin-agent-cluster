"""Read-only and append queries for node lifecycle data."""

from __future__ import annotations

import logging

from backend.db.postgres import raw_conn
from backend.langgraph.lifecycle.errors import LIFECYCLE_DB_ERROR
from backend.langgraph.lifecycle.threads.nodes.sql import _APPEND_NODE_TASK_ID

logger = logging.getLogger(__name__)


async def read_node_output(node_id: str) -> dict:
    """Read the execution output for a completed node.

    Queries the read replica first.  Falls back to the primary when the
    replica has not yet synced a recently-completed node (status still shows
    as ``running`` or ``pending`` due to replication lag).

    Only returns output when the node ``status`` is ``completed``.  Returns
    an empty dict when the node is still in-flight, failed, or cancelled so
    that callers do not proceed on an incomplete predecessor.

    For Mirror nodes the stored output is ``{"task_id": "..."}`` — this
    function transparently resolves the reference by fetching the
    corresponding row from ``fin_agents.task_executions``.

    Args:
        node_id: UUID5-derived node ID.

    Returns:
        The resolved ``output`` JSONB dict.
        Returns an empty dict if the node is not completed or no row exists.
    """
    _QUERY = """
        SELECT n.status, n.view_type, ne.output
        FROM fin_agents.node_executions ne
        JOIN fin_agents.nodes n ON n.node_id = ne.node_id
        WHERE ne.node_id = %s
    """

    async def _query_row(readonly: bool):
        async with raw_conn(readonly=readonly) as conn:
            cur = await conn.execute(_QUERY, (node_id,))
            return await cur.fetchone()

    try:
        row = await _query_row(readonly=True)
        # Replica may lag behind primary for recently-completed nodes;
        # fall back to primary if the row is absent or still in-flight.
        if row is None or row["status"] in ("running", "pending"):
            row = await _query_row(readonly=False)
    except Exception as exc:
        logger.error(
            "[%s] read_node_output DB error node_id=%s: %s",
            LIFECYCLE_DB_ERROR, node_id, exc,
        )
        raise

    if not row or row["status"] != "completed":
        return {}

    if row["view_type"] == "Mirror" and row["output"] and "task_id" in row["output"]:
        task_id = row["output"]["task_id"]
        try:
            async with raw_conn(readonly=True) as conn:
                cur = await conn.execute(
                    "SELECT output FROM fin_agents.task_executions WHERE task_id = %s ORDER BY retry_num DESC LIMIT 1",
                    (task_id,),
                )
                task_row = await cur.fetchone()
            return task_row["output"] if task_row else {}
        except Exception as exc:
            logger.error(
                "[%s] read_node_output DB error node_id=%s task_id=%s: %s",
                LIFECYCLE_DB_ERROR, node_id, task_id, exc,
            )
            raise

    return row["output"] or {}


async def get_latest_sibling_node_version(
    thread_id: str,
    node_name: str,
) -> int:
    """Return the latest completed version of a parallel sibling node.

    Used by the parallel sibling shortcut.  The sibling's latest completed
    version is independent of the forked node's ``fork_source_version`` —
    it reflects all re-explores of the sibling that have happened so far,
    regardless of which other parallel node triggered the current fork.

    Args:
        thread_id: LangGraph thread UUID.
        node_name: Sibling node name to look up.

    Returns:
        Highest completed version, or 0 if none exists.
    """
    try:
        async with raw_conn(readonly=True) as conn:
            cur = await conn.execute(
                "SELECT COALESCE(MAX(version), 0) AS v"
                " FROM fin_agents.nodes"
                " WHERE thread_id = %s AND node_name = %s AND status = 'completed'",
                (thread_id, node_name),
            )
            row = await cur.fetchone()
        return int(row["v"]) if row else 0
    except Exception as exc:
        logger.error(
            "[%s] get_latest_sibling_node_version DB error node_name=%s: %s",
            LIFECYCLE_DB_ERROR, node_name, exc,
        )
        raise


async def append_node_task_id(
    thread_id: str,
    node_id: str,
    task_id: str,
) -> None:
    """Append a task_id to the node's task_ids array in the nodes table.

    Called by ``create_task`` after persisting the task row so that the
    node record always reflects all tasks it has spawned.

    Args:
        thread_id: LangGraph thread UUID.
        node_id:   UUID5-derived node ID.
        task_id:   UUID4 task ID to append.
    """
    try:
        async with raw_conn() as conn:
            await conn.execute(
                _APPEND_NODE_TASK_ID,
                (task_id, node_id, thread_id),
            )
    except Exception as exc:
        logger.error(
            "[%s] append_node_task_id DB error node_id=%s task_id=%s: %s",
            LIFECYCLE_DB_ERROR, node_id, task_id, exc,
        )
        raise


__all__ = [
    "read_node_output",
    "get_latest_sibling_node_version",
    "append_node_task_id",
]
