"""upsert_node and its parallel-snapshot sync helpers."""

from __future__ import annotations

import asyncio
import json
import logging
import time
from typing import Any

from backend.db.postgres import raw_conn
from backend.db.postgres.types import NodeType
from backend.langgraph.lifecycle.errors import LIFECYCLE_DB_ERROR
from backend.langgraph.lifecycle.threads.nodes.sql import (
    _INSERT_NODE_EXECUTION,
    _PROPAGATE_TO_PARALLEL_SIBLINGS,
    _REFRESH_OWN_PARALLEL_SNAPSHOT,
    _UPSERT_NODE,
)
from backend.langgraph.lifecycle.threads.nodes.sse import emit_node_sse

logger = logging.getLogger(__name__)

_DEADLOCK_MAX_RETRIES = 3
_DEADLOCK_BASE_DELAY = 0.05  # 50ms base, doubles each retry


def _is_deadlock(exc: Exception) -> bool:
    """Return True when *exc* is a PostgreSQL deadlock-detected error."""
    exc_msg = str(exc).lower()
    return "deadlock detected" in exc_msg or "40p01" in exc_msg


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

    Both steps are best-effort: on deadlock (which can occur when multiple
    parallel nodes start concurrently and each tries to update sibling rows),
    the operation is retried with exponential backoff.  If retries are
    exhausted the error is logged as a warning and the node proceeds —
    snapshots will eventually converge as other sibling nodes sync.

    Args:
        thread_id:       LangGraph thread UUID.
        node_id:         The node that just started (result of ``_UPSERT_NODE``).
        parallel_group:  Shared label for the concurrent node group.
        parallel_branch: This node's branch identity within the group.
        parent_node_id:  Parent subgraph node ID (``None`` for top-level nodes).
    """

    async def _run_with_retry(label: str, sql: str, params: tuple) -> None:
        for attempt in range(_DEADLOCK_MAX_RETRIES):
            try:
                async with raw_conn() as conn:
                    await conn.execute(sql, params)
                return
            except Exception as exc:
                if _is_deadlock(exc) and attempt < _DEADLOCK_MAX_RETRIES - 1:
                    delay = _DEADLOCK_BASE_DELAY * (2 ** attempt)
                    logger.warning(
                        "[lifecycle] _sync_parallel_snapshots %s deadlock retry "
                        "%d/%d node_id=%s delay=%.3fs",
                        label, attempt + 1, _DEADLOCK_MAX_RETRIES, node_id, delay,
                    )
                    await asyncio.sleep(delay)
                    continue
                if _is_deadlock(exc):
                    logger.warning(
                        "[%s] _sync_parallel_snapshots %s deadlock exhausted "
                        "retries node_id=%s — snapshots will converge lazily",
                        LIFECYCLE_DB_ERROR, label, node_id,
                    )
                    return  # non-fatal: best-effort sync
                logger.error(
                    "[%s] _sync_parallel_snapshots %s error node_id=%s: %s",
                    LIFECYCLE_DB_ERROR, label, node_id, exc,
                )
                raise

    await _run_with_retry(
        "refresh_own",
        _REFRESH_OWN_PARALLEL_SNAPSHOT,
        (thread_id, parallel_group, parent_node_id, parallel_branch, node_id),
    )
    await _run_with_retry(
        "propagate",
        _PROPAGATE_TO_PARALLEL_SIBLINGS,
        (parallel_branch, node_id, node_id, parallel_branch, parallel_branch, parallel_branch),
    )


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
    effective_branch = parallel_branch or (node_name if parallel_group else None)

    t0 = time.monotonic()
    try:
        async with raw_conn() as conn:
            logger.info(
                "[lifecycle:upsert_node] upserting node node_id=%s thread_id=%s "
                "node_name=%s node_type=%s version=%s",
                node_id, thread_id, node_name, node_type, version,
            )
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
        "[lifecycle:node] running node_id=%s node_name=%s db_ms=%.0f -- emitting SSE",
        node_id, node_name, (time.monotonic() - t0) * 1000,
    )
    t_sse = time.monotonic()
    await emit_node_sse(thread_id, node_id, node_name, status="running", payload={"input": input_data or {}})
    logger.debug(
        "[lifecycle:node] running SSE done node_id=%s node_name=%s sse_ms=%.0f",
        node_id, node_name, (time.monotonic() - t_sse) * 1000,
    )


__all__ = ["upsert_node"]
