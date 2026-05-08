"""Node execution logging utility — persists I/O and timing to node_executions."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

_TERMINAL_STATUSES: frozenset[str] = frozenset({"completed", "failed", "cancelled"})

# Maximum recursion depth for Reference node resolution to guard against cycles.
_MAX_REFERENCE_DEPTH: int = 10


async def upsert_node_record(
    node_id: str,
    thread_id: str,
    node_name: str,
    status: str,
    node_execution_id: int,
    executed_at: datetime,
    node_type: str = "Typical",
    referenced_node_id: Optional[str] = None,
) -> None:
    """Upsert a row in ``fin_agents.nodes`` when a node reaches a terminal status.

    Uses ``INSERT … ON CONFLICT DO UPDATE`` so the first execution creates the
    row and subsequent executions update the status fields atomically.
    Only called for terminal statuses (``'completed'``, ``'failed'``, ``'cancelled'``).

    Args:
        node_id:             Governance UUID identifying this node instance (PK in ``nodes``).
        thread_id:           Thread the node belongs to.
        node_name:           LangGraph node name.
        status:              Terminal status — ``'completed'``, ``'failed'``, or ``'cancelled'``.
        node_execution_id:   FK to the ``node_executions`` row for this run.
        executed_at:         Wall-clock timestamp of the node's terminal transition.
        node_type:           Node classification — ``'Typical'``, ``'Subgraph'``, or
                             ``'Reference'``.  Defaults to ``'Typical'``.
        referenced_node_id:  For ``'Reference'`` nodes: the target ``node_id`` within
                             the same thread.  ``None`` for other types.
    """
    if status not in _TERMINAL_STATUSES:
        return

    from sqlalchemy.dialects.postgresql import insert as pg_insert

    from backend.db.postgres.engine import get_session_factory as _get_session_factory
    from backend.graph.models import Node

    factory = _get_session_factory()
    async with factory() as session:
        stmt = (
            pg_insert(Node)
            .values(
                node_id=node_id,
                thread_id=thread_id,
                node_name=node_name,
                type=node_type,
                referenced_node_id=referenced_node_id,
                last_status=status,
                last_node_execution_id=node_execution_id,
                last_executed_at=executed_at,
            )
            .on_conflict_do_update(
                index_elements=["node_id"],
                set_={
                    "last_status": status,
                    "last_node_execution_id": node_execution_id,
                    "last_executed_at": executed_at,
                    "updated_at": executed_at,
                },
            )
        )
        await session.execute(stmt)
        await session.commit()


async def resolve_node_reference(
    node_id: str,
    thread_id: str,
    _depth: int = 0,
) -> Optional[object]:
    """Recursively resolve a Reference node to its Typical or Subgraph target.

    Follows the ``referenced_node_id`` chain in ``fin_agents.nodes`` until a
    non-Reference node is reached.  Returns ``None`` if the node is not found.

    Args:
        node_id:   Starting ``node_id`` to resolve.
        thread_id: Thread the nodes belong to (all nodes in a chain share the
                   same thread).
        _depth:    Internal recursion counter — do not pass from call sites.

    Returns:
        The resolved :class:`~backend.graph.models.Node` ORM instance whose
        type is ``'Typical'`` or ``'Subgraph'``, or ``None`` if not found.

    Raises:
        RecursionError: If the Reference chain exceeds ``_MAX_REFERENCE_DEPTH``
                        (indicates a cycle or misconfigured registry).
    """
    if _depth > _MAX_REFERENCE_DEPTH:
        raise RecursionError(
            f"Reference chain exceeded max depth {_MAX_REFERENCE_DEPTH} "
            f"at node_id={node_id!r} thread_id={thread_id!r}"
        )

    from sqlalchemy import select

    from backend.db.postgres.engine import get_session_factory as _get_session_factory
    from backend.graph.models import Node

    factory = _get_session_factory()
    async with factory() as session:
        row = await session.scalar(
            select(Node).where(
                Node.node_id == node_id,
                Node.thread_id == thread_id,
            )
        )

    if row is None:
        return None
    if row.type != "Reference":
        return row
    if row.referenced_node_id is None:
        return None
    return await resolve_node_reference(row.referenced_node_id, thread_id, _depth + 1)


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
            .returning(
                NodeExecution.started_at,
                NodeExecution.node_name,
                NodeExecution.node_uuid,
                NodeExecution.thread_id,
            )
        )
        row = result.fetchone()
        started_at: datetime = row[0]
        node_name: str = row[1]
        node_uuid: Optional[str] = row[2]
        thread_id: str = row[3]
        await session.commit()
    ended_at = datetime.fromtimestamp(
        started_at.timestamp() + elapsed_ms / 1000.0, tz=started_at.tzinfo
    )
    if node_uuid is not None:
        from backend.graph.agents.node_types import get_node_type
        await upsert_node_record(
            node_uuid,
            thread_id,
            node_name,
            status,
            node_execution_id,
            ended_at,
            node_type=get_node_type(node_name),
        )
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
        result = await session.execute(
            sa_update(NodeExecution)
            .where(NodeExecution.id == node_execution_id)
            .values(status=status)
            .returning(
                NodeExecution.node_name,
                NodeExecution.node_uuid,
                NodeExecution.thread_id,
            )
        )
        row = result.fetchone()
        await session.commit()
    if row is not None and status in _TERMINAL_STATUSES:
        node_name: str = row[0]
        node_uuid: Optional[str] = row[1]
        thread_id: str = row[2]
        if node_uuid is not None:
            from backend.graph.agents.node_types import get_node_type
            await upsert_node_record(
                node_uuid,
                thread_id,
                node_name,
                status,
                node_execution_id,
                datetime.now(timezone.utc),
                node_type=get_node_type(node_name),
            )


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
    ended_at = datetime.fromtimestamp(
        started_at.timestamp() + elapsed_ms / 1000.0, tz=started_at.tzinfo
    )
    await upsert_node_record(node_name, status, node_execution_id, ended_at)
    return node_execution_id

