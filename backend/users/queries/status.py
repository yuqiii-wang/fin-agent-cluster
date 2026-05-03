"""Service logic for reading query status, tasks, and node executions."""

from __future__ import annotations

from fastapi import HTTPException
from sqlalchemy import select

from backend.api.errors import API_QUERY_NOT_FOUND
from backend.db import get_session_factory as _get_session_factory
from backend.graph.models import AgentTask, NodeExecution
from backend.users.models import UserQuery
from backend.users.schemas import NodeExecutionInfo, QueryResponse, SessionStatus, TaskInfo


async def get_query_status(thread_id: str) -> QueryResponse:
    """Return the current status of a submitted query.

    Args:
        thread_id: The UUID returned when the query was submitted.

    Returns:
        ``QueryResponse`` reflecting the current *status* and any *error*.

    Raises:
        404: Thread not found.
    """
    factory = _get_session_factory()
    async with factory() as session:
        row = await session.scalar(
            select(UserQuery).where(UserQuery.thread_id == thread_id)
        )

    if not row:
        raise HTTPException(
            status_code=404,
            detail={"code": API_QUERY_NOT_FOUND, "message": "Query not found"},
        )

    return QueryResponse(
        thread_id=row.thread_id,
        status=row.status,
        report=row.answer,
        error=row.error,
    )


async def get_query_tasks(thread_id: str) -> SessionStatus:
    """Return the query record and all its agent sub-tasks.

    Args:
        thread_id: The UUID returned when the query was submitted.

    Returns:
        ``SessionStatus`` containing the query status and a list of
        ``TaskInfo`` records — one per sub-task across all nodes.

    Raises:
        404: Thread not found.
    """
    factory = _get_session_factory()
    async with factory() as session:
        uq_row = await session.scalar(
            select(UserQuery).where(UserQuery.thread_id == thread_id)
        )
        if not uq_row:
            raise HTTPException(
                status_code=404,
                detail={"code": API_QUERY_NOT_FOUND, "message": "Query not found"},
            )

        tasks_result = await session.execute(
            select(AgentTask)
            .where(AgentTask.thread_id == thread_id)
            .order_by(AgentTask.created_at)
        )
        task_rows = tasks_result.scalars().all()

    return SessionStatus(
        thread_id=thread_id,
        user_query_id=uq_row.id,
        status=uq_row.status,
        tasks=[
            TaskInfo(
                id=t.id,
                thread_id=t.thread_id,
                node_execution_id=t.node_execution_id,
                node_name=t.node_name,
                task_name=t.task_name,
                status=t.status,
                input=t.input,
                output=t.output,
                created_at=t.created_at,
                updated_at=t.updated_at,
            )
            for t in task_rows
        ],
    )


async def get_node_executions(thread_id: str) -> list[NodeExecutionInfo]:
    """Return node-level input/output snapshots for a thread.

    Each entry corresponds to one node invocation and contains the full
    ``input`` state fed into the node and the ``output`` state diff it
    returned.

    Args:
        thread_id: The UUID returned when the query was submitted.

    Returns:
        List of :class:`NodeExecutionInfo` ordered by execution start time.
    """
    factory = _get_session_factory()
    async with factory() as session:
        result = await session.execute(
            select(NodeExecution)
            .where(NodeExecution.thread_id == thread_id)
            .order_by(NodeExecution.started_at)
        )
        rows = result.scalars().all()

    return [
        NodeExecutionInfo(
            id=r.id,
            node_name=r.node_name,
            node_uuid=r.node_uuid,
            status=r.status,
            input=r.input,
            output=r.output,
            started_at=r.started_at,
            elapsed_ms=r.elapsed_ms,
        )
        for r in rows
    ]
