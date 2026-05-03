"""Node execution logging utility — persists I/O and timing to node_executions."""

from __future__ import annotations

from datetime import datetime
from typing import Optional


async def start_node_execution(
    thread_id: str,
    node_name: str,
    input_data: dict,
    started_at: datetime,
    node_uuid: Optional[str] = None,
    parent_node_execution_id: Optional[int] = None,
) -> int:
    """Insert a new node_executions row at the start of a node and return its id.

    Output and elapsed_ms are initialised to empty / zero and should be filled
    in by a subsequent call to :func:`finish_node_execution`.

    Args:
        thread_id:                 LangGraph thread UUID.
        node_name:                 Node name identifier.
        input_data:                Input snapshot for the node.
        started_at:                Wall-clock start time (UTC).
        node_uuid:                 Governance UUID for this node execution; links the PG row
                                   to the Redis governance registry for cancel/status scoping.
        parent_node_execution_id:  FK to the parent ``node_executions`` row when this node
                                   runs inside a subgraph.  ``None`` for top-level nodes.

    Returns:
        The primary-key ``id`` of the new ``NodeExecution`` row.
    """
    from backend.db.postgres.engine import get_session_factory as _get_session_factory
    from backend.graph.models import NodeExecution

    factory = _get_session_factory()
    async with factory() as session:
        record = NodeExecution(
            thread_id=thread_id,
            node_name=node_name,
            node_uuid=node_uuid,
            parent_node_execution_id=parent_node_execution_id,
            input=input_data,
            output={},
            started_at=started_at,
            elapsed_ms=0,
        )
        session.add(record)
        await session.flush()
        node_execution_id: int = record.id
        await session.commit()
    return node_execution_id


async def finish_node_execution(
    node_execution_id: int,
    output_data: dict,
    elapsed_ms: int,
    status: str = "completed",
) -> datetime:
    """Update an existing node_executions row with its final output and elapsed time.

    Uses a single ``UPDATE … RETURNING started_at`` round-trip so the caller
    can derive the authoritative ``ended_at_ms`` as
    ``int(started_at.timestamp() * 1000) + elapsed_ms`` without an extra
    SELECT — keeping timestamps invariant to wall-clock drift at emit time.

    Args:
        node_execution_id: PK returned by :func:`start_node_execution`.
        output_data:       Snapshot of node outputs serialised as a plain dict.
        elapsed_ms:        Wall-clock duration of the node in milliseconds.
        status:            Terminal status — ``'completed'``, ``'failed'``, or
                           ``'cancelled'``.  Defaults to ``'completed'``.

    Returns:
        The ``started_at`` timestamp committed to the DB row, used to derive
        the authoritative ``ended_at_ms``.
    """
    from sqlalchemy import update as sa_update

    from backend.db.postgres.engine import get_session_factory as _get_session_factory
    from backend.graph.models import NodeExecution

    factory = _get_session_factory()
    async with factory() as session:
        result = await session.execute(
            sa_update(NodeExecution)
            .where(NodeExecution.id == node_execution_id)
            .values(output=output_data, elapsed_ms=elapsed_ms, status=status)
            .returning(NodeExecution.started_at)
        )
        row = result.fetchone()
        started_at: datetime = row[0]
        await session.commit()
    return started_at


async def update_node_execution_status(
    node_execution_id: int,
    status: str,
) -> None:
    """Update only the status of an existing node_executions row.

    Used for mid-flight status transitions (e.g. 'running' → 'cancelled')
    without overwriting output or elapsed_ms.

    Args:
        node_execution_id: PK returned by :func:`start_node_execution`.
        status:            New status value.
    """
    from sqlalchemy import update as sa_update

    from backend.db.postgres.engine import get_session_factory as _get_session_factory
    from backend.graph.models import NodeExecution

    factory = _get_session_factory()
    async with factory() as session:
        await session.execute(
            sa_update(NodeExecution)
            .where(NodeExecution.id == node_execution_id)
            .values(status=status)
        )
        await session.commit()


async def log_node_execution(
    thread_id: str,
    node_name: str,
    input_data: dict,
    output_data: dict,
    started_at: datetime,
    elapsed_ms: int,
    node_uuid: Optional[str] = None,
    parent_node_execution_id: Optional[int] = None,
    status: str = "completed",
) -> int:
    """Insert a complete node execution record in a single call.

    Convenience wrapper for callers that don't need the start/finish split.

    Args:
        thread_id:                 LangGraph thread UUID.
        node_name:                 Node name identifier.
        input_data:                Input snapshot.
        output_data:               Output snapshot.
        started_at:                Wall-clock start time (UTC).
        elapsed_ms:                Total elapsed milliseconds.
        node_uuid:                 Governance UUID (optional).
        parent_node_execution_id:  FK to parent node execution (optional).
        status:                    Terminal status (defaults to ``'completed'``).

    Returns:
        The new row's primary-key id.
    """
    from backend.db.postgres.engine import get_session_factory as _get_session_factory
    from backend.graph.models import NodeExecution

    factory = _get_session_factory()
    async with factory() as session:
        record = NodeExecution(
            thread_id=thread_id,
            node_name=node_name,
            node_uuid=node_uuid,
            parent_node_execution_id=parent_node_execution_id,
            input=input_data,
            output=output_data,
            started_at=started_at,
            elapsed_ms=elapsed_ms,
            status=status,
        )
        session.add(record)
        await session.flush()
        node_execution_id: int = record.id
        await session.commit()
    return node_execution_id

