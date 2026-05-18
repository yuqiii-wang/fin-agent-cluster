"""Public API for node-level lifecycle operations."""

from __future__ import annotations

import json
import logging
import time
from typing import Any

from backend.db.postgres import raw_conn
from backend.db.postgres.types import NodeType
from backend.langgraph.lifecycle.errors import (
    LIFECYCLE_CANCEL_FAILED,
    LIFECYCLE_DB_ERROR,
)
from backend.langgraph.lifecycle.threads.nodes.sql import (
    _APPEND_NODE_TASK_ID,
    _CANCEL_ACTIVE_TASKS_BY_NODE,
    _CANCEL_NODE_SELF,
    _INSERT_NODE_EXECUTION,
    _PROPAGATE_TO_PARALLEL_SIBLINGS,
    _REFRESH_OWN_PARALLEL_SNAPSHOT,
    _UPDATE_NODE_COMPLETED,
    _UPDATE_NODE_EXECUTION_OUTPUT,
    _UPDATE_NODE_NEXT_IDS,
    _UPSERT_NODE,
)
from backend.langgraph.lifecycle.threads.nodes.sse import (
    emit_node_sse,
    emit_task_cancelled_sse,
)

logger = logging.getLogger(__name__)


def get_thread_registry():
    """Lazy import to avoid circular imports at module load time."""
    from backend.langgraph.lifecycle.threads.manager import (
        get_thread_registry as _get,
    )
    return _get()


async def _sync_parallel_snapshots(
    thread_id: str,
    node_id: str,
    parallel_group: str,
    parallel_branch: str,
    parent_node_id: str | None,
) -> None:
    """Sync cross-branch parallel snapshots for a node that belongs to a parallel group.

    Called immediately after ``_UPSERT_NODE`` when ``parallel_group`` and
    ``parallel_branch`` are both set.  Performs two SQL updates in separate
    connections so each can be retried independently:

    1. **Refresh own snapshot**: sets this node's ``parallel_snapshots`` to the
       latest known node_id per sibling branch (every branch in the same
       ``parallel_group`` / ``parent_node_id`` whose ``parallel_branch`` != ours,
       ordered by ``started_at DESC`` so the freshest node wins).

    2. **Propagate to siblings**: writes this node's ``node_id`` into every
       sibling node's ``parallel_snapshots[parallel_branch]``, but only when
       the currently stored node_id for that branch started earlier than this
       node (guards against sequential ordering: a2 must not be replaced by a1).

    Together these two operations ensure that, for any node X in a parallel group,
    ``X.parallel_snapshots`` always reflects the most-recently-started node from
    every other branch — and is retroactively updated as those branches advance.

    Args:
        thread_id:       LangGraph thread UUID.
        node_id:         The node that just started (result of ``_UPSERT_NODE``).
        parallel_group:  Shared label for the concurrent node group.
        parallel_branch: This node's branch identity within the group.
        parent_node_id:  Parent subgraph node ID (``None`` for top-level nodes).
    """
    try:
        async with raw_conn() as conn:
            await conn.execute(
                _REFRESH_OWN_PARALLEL_SNAPSHOT,
                (thread_id, parallel_group, parent_node_id, parallel_branch, node_id),
            )
    except Exception as exc:
        logger.error(
            "[%s] _sync_parallel_snapshots refresh_own error node_id=%s: %s",
            LIFECYCLE_DB_ERROR, node_id, exc,
        )
        raise

    try:
        async with raw_conn() as conn:
            await conn.execute(
                _PROPAGATE_TO_PARALLEL_SIBLINGS,
                (parallel_branch, node_id, node_id, parallel_branch, parallel_branch, parallel_branch),
            )
    except Exception as exc:
        logger.error(
            "[%s] _sync_parallel_snapshots propagate error node_id=%s: %s",
            LIFECYCLE_DB_ERROR, node_id, exc,
        )
        raise


async def upsert_node(
    thread_id: str,
    node_id: str,
    node_name: str,
    node_type: str = NodeType.WORKFLOW,
    parent_node_id: str | None = None,
    input_data: dict[str, Any] | None = None,
    parallel_group: str | None = None,
    parallel_branch: str | None = None,
    version: int = 0,
    checkpoint_id: str = "",
    prev_node_ids: list[str] | None = None,
    is_forked: bool = False,
    forked_from_version: int | None = None,
    view_type: str = "Json",
    view_schema: dict[str, Any] | None = None,
    stats_views: list[str] | None = None,
) -> None:
    """Persist a node execution row (INSERT or UPDATE to running).

    Writes topology to ``fin_agents.nodes`` and execution payload to
    ``fin_agents.node_executions`` in the same connection.

    Safe to call multiple times for the same node; subsequent calls update
    the checkpoint_id/prev_node_ids and reset status to running (unless
    already terminal).

    Emits a ``node_status: running`` SSE event after the DB write.

    If the node belongs to a parallel group (``parallel_group`` and
    ``parallel_branch`` are both set), the call also:
    - Refreshes this node's ``parallel_snapshots`` with the latest node_id
      from every sibling branch currently known in the DB.
    - Propagates this node as the new latest for its branch to all sibling
      nodes' ``parallel_snapshots``, replacing any older node_id for the
      same branch.

    Args:
        thread_id:           LangGraph thread UUID.
        node_id:             UUID5-derived stable node ID (from ``make_node_id``).
        node_name:           Human-readable node name.
        node_type:           ``"Workflow"`` or ``"Subgraph"``.
        parent_node_id:      Parent subgraph node ID, or ``None`` for top-level nodes.
        input_data:          Serialisable input payload (written to node_executions).
        parallel_group:      Shared label for nodes that run concurrently within
            the same parent subgraph.  ``None`` for sequential nodes.
        parallel_branch:     Branch identifier within the parallel_group.  Must be
            set alongside ``parallel_group``.  Defaults to ``node_name`` if the
            caller passes ``parallel_group`` but omits this.
        version:             Fork generation counter (``GraphState.fork_generation``).
        checkpoint_id:       LangGraph checkpoint ID at node start.
        prev_node_ids:       Predecessor node IDs in the current branch.
        is_forked:           ``True`` for the first node of a re-explore fork branch.
        forked_from_version: Version that this fork branched from; set on the
            is_forked node and all sibling nodes in the same version.
        view_type:           ``fin_agents.node_view_types`` value for this node
            (``"Json"``, ``"Mirror"``, ``"Hybrid"``, etc.).
        view_schema:         Per-field rendering schema used with ``Mirror`` and
            ``Hybrid`` view types.  ``Mirror``: ``{"task_id": "<id>"}``.  ``Hybrid``:
            ``{"<field>": "<view_type>" | {"type": "Mirror", "task_id": "<id>"}}""}``.
    """
    from backend.main_thread.context import get_fencing_token
    fencing_token = get_fencing_token()

    prev_ids = prev_node_ids or []
    views = stats_views or []
    # Infer parallel_branch from node_name when group is set but branch omitted.
    effective_branch = parallel_branch or (node_name if parallel_group else None)

    t0 = time.monotonic()
    try:
        async with raw_conn() as conn:
            await conn.execute(
                _UPSERT_NODE,
                (
                    node_id, thread_id, version, node_type, parent_node_id,
                    node_name, checkpoint_id, prev_ids,
                    parallel_group, effective_branch, fencing_token,
                    is_forked, forked_from_version, view_type,
                    json.dumps(view_schema or {}), views,
                ),
            )
            await conn.execute(
                _INSERT_NODE_EXECUTION,
                (node_id, json.dumps(input_data or {})),
            )
    except Exception as exc:
        logger.error(
            "[%s] upsert_node DB error node_id=%s thread_id=%s: %s",
            LIFECYCLE_DB_ERROR, node_id, thread_id, exc,
        )
        raise

    if parallel_group and effective_branch:
        await _sync_parallel_snapshots(
            thread_id=thread_id,
            node_id=node_id,
            parallel_group=parallel_group,
            parallel_branch=effective_branch,
            parent_node_id=parent_node_id,
        )

    logger.debug(
        "[lifecycle:node] running node_id=%s node_name=%s db_ms=%.0f — emitting SSE",
        node_id, node_name, (time.monotonic() - t0) * 1000,
    )
    t_sse = time.monotonic()
    await emit_node_sse(thread_id, node_id, node_name, status="running", payload={"input": input_data or {}})
    logger.debug(
        "[lifecycle:node] running SSE done node_id=%s node_name=%s sse_ms=%.0f",
        node_id, node_name, (time.monotonic() - t_sse) * 1000,
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
            "[lifecycle:node] %s skipped node_id=%s node_name=%s existing_status=%s — node already terminal",
            status, node_id, node_name, _existing,
        )
        return  # Already terminal — skip SSE.

    logger.debug(
        "[lifecycle:node] %s node_id=%s node_name=%s db_ms=%.0f — emitting SSE",
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


async def read_node_output(node_id: str) -> dict[str, Any]:
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
                    "SELECT output FROM fin_agents.task_executions WHERE task_id = %s",
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

    For example, if ``analyze_stats_node`` was re-explored to v1, and then
    ``analyze_news_node`` is re-explored (its fork_source_version=0 because
    news was at v0), the sibling lookup must return stats v1 — not v0.
    Bounding by fork_source_version=0 would incorrectly exclude stats_v1.

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


async def cancel_node(
    thread_id: str,
    node_id: str,
    *,
    reason: str = "user",
) -> bool:
    """Cancel a node and all its active tasks, then emit SSE.

    Cascade order:
    1. Revoke all tracked Celery tasks for the node.
    2. Bulk-UPDATE active tasks to ``cancelled`` (RETURNING task_ids for SSE).
    3. UPDATE the node itself to ``cancelled``.
    4. Emit SSE for each cancelled task, then for the node.

    Args:
        thread_id: LangGraph thread UUID.
        node_id:   Node ID to cancel.
        reason:    Human-readable cancellation reason.

    Returns:
        ``True`` if the node was active and has been cancelled;
        ``False`` if it was already terminal.
    """
    # ------------------------------------------------------------------
    # 1. Revoke in-flight Celery tasks for this node.
    # ------------------------------------------------------------------
    try:
        async with raw_conn(readonly=True) as conn:
            cur = await conn.execute(
                "SELECT task_id FROM fin_agents.tasks WHERE node_id = %s "
                "AND thread_id = %s "
                "AND status NOT IN ('completed','failed','cancelled','wrong')",
                (node_id, thread_id),
            )
            active_task_ids = [r["task_id"] for r in await cur.fetchall()]

        registry = get_thread_registry()
        for tid in active_task_ids:
            registry.revoke_celery_task(tid)
    except Exception as exc:  # noqa: BLE001
        logger.error(
            "[%s] cancel_node revoke failed node_id=%s: %s",
            LIFECYCLE_CANCEL_FAILED, node_id, exc,
        )

    # ------------------------------------------------------------------
    # 2 & 3. Batch DB updates (tasks first, then node).
    # ------------------------------------------------------------------
    node_cancelled = False

    try:
        async with raw_conn() as conn:
            cur = await conn.execute(
                _CANCEL_ACTIVE_TASKS_BY_NODE, (node_id, thread_id)
            )
            cancelled_task_rows = await cur.fetchall()

            cur2 = await conn.execute(_CANCEL_NODE_SELF, (node_id, thread_id))
            node_cancelled = cur2.rowcount > 0
    except Exception as exc:
        logger.error(
            "[%s] cancel_node DB error node_id=%s: %s",
            LIFECYCLE_DB_ERROR, node_id, exc,
        )
        raise

    if not node_cancelled:
        return False  # Already terminal.

    # ------------------------------------------------------------------
    # 3b. Set per-node cancel flag in Redis so the delegation poll loop
    #     for this node's tasks exits within one cycle (avoids the 120 s
    #     task timeout when the node was cancelled mid-execution).
    # ------------------------------------------------------------------
    try:
        from backend.main_thread.cancel_flag import set_node_cancel_flag
        await set_node_cancel_flag(node_id)
    except Exception as exc:  # noqa: BLE001
        logger.error(
            "[%s] cancel_node set_node_cancel_flag failed node_id=%s: %s",
            LIFECYCLE_CANCEL_FAILED, node_id, exc,
        )

    # ------------------------------------------------------------------
    # 4. SSE — tasks first, then node.
    # ------------------------------------------------------------------
    for row in cancelled_task_rows:
        await emit_task_cancelled_sse(
            thread_id,
            row["task_id"],
            task_name=row["task_name"] or "",
            node_name=row["node_name"] or "",
            reason=reason,
        )

    await emit_node_sse(
        thread_id, node_id, node_name="",
        status="cancelled",
        payload={"reason": reason},
    )
    return True


__all__ = [
    "upsert_node",
    "complete_node",
    "cancel_node",
    "read_node_output",
    "append_node_task_id",
]
