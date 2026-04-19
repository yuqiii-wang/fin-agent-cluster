"""Node I/O SSE notifications — emit node input and output update events.

Wraps :func:`~backend.graph.utils.execution_log.start_node_execution` and
:func:`~backend.graph.utils.execution_log.finish_node_execution` with
pg_notify calls so the frontend can display node I/O in real time.

Event flow:
  1. Node starts  → :func:`emit_node_input`  → inserts ``node_executions`` row
     → fires ``node_input``  pg_notify.
  2. Node finishes → :func:`emit_node_output` → updates ``node_executions`` row
     → fires ``node_output`` pg_notify.

These events travel via the same PostgreSQL NOTIFY channel as task lifecycle
events so the existing SSE listener picks them up without extra plumbing.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from backend.sse_notifications.channel import pg_notify

logger = logging.getLogger(__name__)


async def emit_node_input(
    thread_id: str,
    node_name: str,
    input_data: dict,
) -> int:
    """Persist a new node_executions row and emit a ``node_input`` SSE event.

    Must be called at the very start of a LangGraph node before any sub-tasks
    are created.

    Args:
        thread_id:  LangGraph thread UUID.
        node_name:  Name of the node (e.g. ``"market_data_collector"``).
        input_data: Snapshot of the inputs the node received from state.

    Returns:
        DB primary key of the new ``NodeExecution`` row (pass to
        :func:`emit_node_output`).
    """
    from backend.graph.utils.execution_log import start_node_execution  # deferred

    started_at = datetime.now(timezone.utc)
    node_execution_id = await start_node_execution(
        thread_id,
        node_name,
        input_data,
        started_at,
    )
    await pg_notify(
        thread_id,
        {
            "event": "node_input",
            "node_execution_id": node_execution_id,
            "node_name": node_name,
            "input": input_data,
        },
    )
    logger.debug(
        "[node_io] node_input node=%s exec_id=%d thread_id=%s",
        node_name,
        node_execution_id,
        thread_id,
    )
    return node_execution_id


async def emit_node_output(
    thread_id: str,
    node_name: str,
    node_execution_id: int,
    output_data: dict,
    elapsed_ms: int,
) -> None:
    """Update the node_executions row and emit a ``node_output`` SSE event.

    Must be called after a LangGraph node finishes all its sub-tasks.

    Args:
        thread_id:         LangGraph thread UUID.
        node_name:         Name of the node.
        node_execution_id: PK returned by :func:`emit_node_input`.
        output_data:       Snapshot of the node's output written to state.
        elapsed_ms:        Wall-clock duration of the node in milliseconds.
    """
    from backend.graph.utils.execution_log import finish_node_execution  # deferred

    await finish_node_execution(node_execution_id, output_data, elapsed_ms)
    await pg_notify(
        thread_id,
        {
            "event": "node_output",
            "node_execution_id": node_execution_id,
            "node_name": node_name,
            "output": output_data,
            "elapsed_ms": elapsed_ms,
        },
    )
    logger.debug(
        "[node_io] node_output node=%s exec_id=%d elapsed_ms=%d thread_id=%s",
        node_name,
        node_execution_id,
        elapsed_ms,
        thread_id,
    )


__all__ = ["emit_node_input", "emit_node_output"]
