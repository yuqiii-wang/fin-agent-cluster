"""Node execution logging utility — persists I/O and timing to node_executions."""

from __future__ import annotations

from datetime import datetime


async def start_node_execution(
    thread_id: str,
    node_name: str,
    input_data: dict,
    started_at: datetime,
) -> int:
    """Insert a new node_executions row at the start of a node and return its id.

    Output and elapsed_ms are initialised to empty / zero and should be filled
    in by a subsequent call to :func:`finish_node_execution`.

    Returns:
        The primary-key ``id`` of the new ``NodeExecution`` row.
    """
    from backend.db.engine import get_session_factory as _get_session_factory
    from backend.graph.models import NodeExecution

    factory = _get_session_factory()
    async with factory() as session:
        record = NodeExecution(
            thread_id=thread_id,
            node_name=node_name,
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
) -> None:
    """Update an existing node_executions row with its final output and elapsed time.

    Args:
        node_execution_id: PK returned by :func:`start_node_execution`.
        output_data:       Snapshot of node outputs serialised as a plain dict.
        elapsed_ms:        Wall-clock duration of the node in milliseconds.
    """
    from sqlalchemy import update as sa_update

    from backend.db.engine import get_session_factory as _get_session_factory
    from backend.graph.models import NodeExecution

    factory = _get_session_factory()
    async with factory() as session:
        await session.execute(
            sa_update(NodeExecution)
            .where(NodeExecution.id == node_execution_id)
            .values(output=output_data, elapsed_ms=elapsed_ms)
        )
        await session.commit()


async def log_node_execution(
    thread_id: str,
    node_name: str,
    input_data: dict,
    output_data: dict,
    started_at: datetime,
    elapsed_ms: int,
) -> int:
    """Insert a complete node execution record in a single call.

    Kept for backward compatibility with callers that don't need the
    start/finish split.  Returns the new row's primary-key id.
    """
    from backend.db.engine import get_session_factory as _get_session_factory
    from backend.graph.models import NodeExecution

    factory = _get_session_factory()
    async with factory() as session:
        record = NodeExecution(
            thread_id=thread_id,
            node_name=node_name,
            input=input_data,
            output=output_data,
            started_at=started_at,
            elapsed_ms=elapsed_ms,
        )
        session.add(record)
        await session.flush()
        node_execution_id: int = record.id
        await session.commit()
    return node_execution_id
