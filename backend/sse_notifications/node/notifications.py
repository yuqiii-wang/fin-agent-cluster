"""Node I/O SSE notifications — emit node input, output, and status events.

Wraps :func:`~backend.graph.utils.execution_log.start_node_execution` and
:func:`~backend.graph.utils.execution_log.finish_node_execution` with
Centrifugo publishes so the frontend can display node I/O in real time.

Timestamp invariance
--------------------
All timestamps in the emitted payloads are derived from the committed
``fin_agents.node_executions`` row — NOT from wall-clock time at emit:

* ``started_at_ms``  — from the ``started_at`` value written to DB by
  :func:`start_node_execution`.
* ``ended_at_ms``    — derived as ``int(started_at.timestamp() * 1000) + elapsed_ms``
  using the ``started_at`` returned by :func:`finish_node_execution` via
  ``UPDATE … RETURNING started_at``.

This ensures that even when the SSE event arrives asynchronously at the
client, the lifecycle timestamps are invariant and match the DB record.

Event flow:
  1. Node starts  → :func:`emit_node_input`  → inserts ``node_executions`` row
     → publishes ``node_input`` to Centrifugo.
  2. Node finishes → :func:`emit_node_output` → updates ``node_executions`` row
     → publishes ``node_output`` to Centrifugo.
     Returns the DB-derived ``ended_at_ms`` for propagation to ``emit_node_status``.
  3. Node status  → :func:`emit_node_status` → publishes ``node_status`` event.
     Accepts the ``ended_at_ms`` returned by :func:`emit_node_output` for the
     completed path; falls back to wall-clock for failed/cancelled paths where
     no ``node_output`` was emitted.
"""

from __future__ import annotations

import logging
import time as _time
from datetime import datetime, timezone
from typing import Optional

from backend.sse_notifications.channel import publish_node_lifecycle

logger = logging.getLogger(__name__)


async def emit_node_input(
    thread_id: str,
    node_name: str,
    input_data: dict,
    node_uuid: Optional[str] = None,
    parent_node_execution_ids: list[int] = [],
) -> tuple[int, float]:
    """Persist a new node_executions row and emit a ``node_input`` SSE event.

    Captures ``started_at`` (wall-clock) and ``t0_mono`` (monotonic) at the
    **same instant** before the DB INSERT so that callers can compute
    ``elapsed_ms = time.monotonic() - t0_mono`` and the invariant
    ``ended_at_ms = started_at_ms + elapsed_ms`` holds exactly.

    Args:
        thread_id:                  LangGraph thread UUID.
        node_name:                  Name of the node.
        input_data:                 Snapshot of the inputs the node received.
        node_uuid:                  Governance UUID for this node execution.
        parent_node_execution_ids:  List of parent node execution PKs (for
                                    fan-in nodes with multiple parents; empty
                                    list for top-level nodes).

    Returns:
        ``(node_execution_id, t0_mono)`` — DB primary key and the monotonic
        reference timestamp captured at the same instant as ``started_at``.
        Use ``int((time.monotonic() - t0_mono) * 1000)`` for ``elapsed_ms``.
    """
    from backend.graph.utils.execution_log import start_node_execution  # deferred

    from backend.graph.agents.node_types import get_node_type, get_node_graph_parent  # deferred

    # DB stores a single FK for the first parent (or None)
    primary_parent = parent_node_execution_ids[0] if parent_node_execution_ids else None
    # Capture wall-clock and monotonic at the same instant so that
    # elapsed_ms = mono_end - t0_mono anchors correctly to started_at.
    started_at = datetime.now(timezone.utc)
    t0_mono = _time.monotonic()
    node_execution_id = await start_node_execution(
        thread_id,
        node_name,
        input_data,
        started_at,
        node_uuid=node_uuid,
        parent_node_execution_id=primary_parent,
    )
    node_type = get_node_type(node_name)
    subgraph_parent = get_node_graph_parent(node_name)
    await publish_node_lifecycle(
        thread_id,
        {
            "event": "node_input",
            "node_execution_id": node_execution_id,
            "node_name": node_name,
            "node_type": node_type,
            "subgraph_parent": subgraph_parent,
            "parent_node_execution_ids": parent_node_execution_ids,
            "input": input_data,
            "started_at_ms": int(started_at.timestamp() * 1000),
        },
    )
    logger.debug(
        "[node] node_input node=%s exec_id=%d parents=%s thread_id=%s",
        node_name,
        node_execution_id,
        parent_node_execution_ids,
        thread_id,
    )
    return node_execution_id, t0_mono


async def emit_node_output(
    thread_id: str,
    node_name: str,
    node_execution_id: int,
    output_data: dict,
    elapsed_ms: int,
) -> int:
    """Update the node_executions row and emit a ``node_output`` SSE event.

    Uses ``UPDATE … RETURNING started_at`` so the emitted ``ended_at_ms`` is
    derived from the DB-committed ``started_at + elapsed_ms``, not from
    wall-clock time at emit.

    Must be called after a LangGraph node finishes all its sub-tasks.

    Args:
        thread_id:         LangGraph thread UUID.
        node_name:         Name of the node.
        node_execution_id: PK returned by :func:`emit_node_input`.
        output_data:       Snapshot of the node's output written to state.
        elapsed_ms:        Wall-clock duration of the node in milliseconds.

    Returns:
        ``ended_at_ms`` derived from the DB-committed ``started_at + elapsed_ms``.
        Callers should pass this to :func:`emit_node_status` for the completed path
        so the status event carries the same invariant timestamp.
    """
    from backend.graph.utils.execution_log import finish_node_execution  # deferred

    started_at: datetime = await finish_node_execution(node_execution_id, output_data, elapsed_ms)
    ended_at_ms: int = int(started_at.timestamp() * 1000) + elapsed_ms
    await publish_node_lifecycle(
        thread_id,
        {
            "event": "node_output",
            "node_execution_id": node_execution_id,
            "node_name": node_name,
            "output": output_data,
            "elapsed_ms": elapsed_ms,
            "ended_at_ms": ended_at_ms,
        },
    )
    logger.debug(
        "[node] node_output node=%s exec_id=%d elapsed_ms=%d thread_id=%s",
        node_name,
        node_execution_id,
        elapsed_ms,
        thread_id,
    )
    return ended_at_ms


async def emit_node_status(
    thread_id: str,
    node_id: str,
    node_name: str,
    status: str,
    ended_at_ms: Optional[int] = None,
) -> None:
    """Publish a ``node_status`` SSE event so the frontend updates per-node indicators.

    Also updates the governance Redis key so status is queryable at runtime.
    This is the single call-site for broadcasting a node lifecycle change —
    callers must also update the PG row via
    :func:`~backend.graph.utils.execution_log.update_node_execution_status`
    (kept separate to avoid coupling execution_log to SSE).

    For the **completed** path, pass the ``ended_at_ms`` returned by
    :func:`emit_node_output` so the status event carries the same DB-derived
    timestamp.  For **failed** / **cancelled** paths (no prior ``node_output``),
    omit ``ended_at_ms`` and the current wall-clock time is used as the best
    available approximation.

    Args:
        thread_id:    LangGraph thread UUID.
        node_id:      Governance UUID of the node execution.
        node_name:    Human-readable node name.
        status:       New status — ``'running'``, ``'completed'``, ``'failed'``,
                      or ``'cancelled'``.
        ended_at_ms:  DB-derived end timestamp in milliseconds since epoch.
                      Pass the value returned by :func:`emit_node_output`
                      for the completed path.  ``None`` for non-terminal statuses
                      or when no node_output was emitted (failed/cancelled).
    """
    from backend.graph.governance.registry import set_node_status  # deferred

    _TERMINAL = {"completed", "failed", "cancelled"}
    await set_node_status(thread_id, node_id, status, node_name)
    payload: dict = {
        "event": "node_status",
        "node_id": node_id,
        "node_name": node_name,
        "status": status,
        "thread_id": thread_id,
    }
    if status in _TERMINAL:
        payload["ended_at_ms"] = (
            ended_at_ms
            if ended_at_ms is not None
            else int(datetime.now(timezone.utc).timestamp() * 1000)
        )
    await publish_node_lifecycle(thread_id, payload)
    logger.debug(
        "[node] node_status node=%s node_id=%s status=%s thread_id=%s",
        node_name, node_id, status, thread_id,
    )


async def emit_graph_topology(thread_id: str, query: str) -> None:
    """Emit a ``graph_topology_init`` SSE event with the query-filtered topology.

    Called once at the start of each graph run so the frontend can pre-populate
    the single routed graph container node before any node events arrive.

    Args:
        thread_id: LangGraph thread UUID.
        query:     Raw query text used to select the routed graph branch.
    """
    from backend.graph.topology import get_graph_topology  # deferred

    topology = get_graph_topology(query)
    await publish_node_lifecycle(
        thread_id,
        {
            "event": "graph_topology_init",
            "outer_nodes": [n.model_dump() for n in topology.outer_nodes],
            "subgraphs": {
                name: {"nodes": [n.model_dump() for n in g.nodes]}
                for name, g in topology.subgraphs.items()
            },
        },
    )


__all__ = ["emit_node_input", "emit_node_output", "emit_node_status", "emit_graph_topology"]
