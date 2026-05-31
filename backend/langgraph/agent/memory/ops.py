"""Read-only access to task outputs that serve as agent memory.

An agent node's memory is the live set of finished task outputs it has produced
within the same node execution.  These helpers project ``fin_agents.tasks`` rows
(joined with the latest ``fin_agents.task_executions`` output) into
:class:`TaskMemory` records — no dedicated memory table is used.
"""

from __future__ import annotations

import logging
from typing import Any

from backend.db.postgres import raw_conn
from backend.langgraph.agent.memory.models import COMPLETED_STATUSES, TaskMemory

logger = logging.getLogger(__name__)


async def get_task_memory(
    node_id: str,
    *,
    statuses: tuple[str, ...] = COMPLETED_STATUSES,
    with_output: bool = True,
) -> list[TaskMemory]:
    """Return task-output memory entries for *node_id*.

    Args:
        node_id:     Agent node UUID.
        statuses:    Task statuses to include (default: completed tasks only).
        with_output: When ``True`` also load each task's latest-retry output
                     payload.  Pass ``False`` for a lightweight descriptor-only
                     listing (task_id / task_name / description) used when the
                     LLM first selects which outputs are worth reading.

    Returns:
        List of :class:`TaskMemory` ordered by task creation time (ascending).
    """
    output_select = ", te.output" if with_output else ""
    output_join = (
        """
        LEFT JOIN LATERAL (
            SELECT output
            FROM fin_agents.task_executions
            WHERE task_id = t.task_id
            ORDER BY retry_num DESC
            LIMIT 1
        ) te ON TRUE
        """
        if with_output
        else ""
    )

    async with raw_conn(readonly=True) as conn:
        cur = await conn.execute(
            f"""
            SELECT t.task_id, t.node_id, t.node_name, t.task_name,
                   t.description, t.status, t.updated_at{output_select}
            FROM fin_agents.tasks t
            {output_join}
            WHERE t.node_id = %s AND t.status = ANY(%s)
            ORDER BY t.created_at ASC
            """,
            (node_id, list(statuses)),
        )
        rows = await cur.fetchall()

    return [
        TaskMemory(
            task_id=str(r["task_id"]),
            node_id=str(r["node_id"]),
            node_name=r["node_name"],
            task_name=r["task_name"],
            description=r["description"],
            status=r["status"],
            output=r["output"] if with_output else None,
            updated_at=r["updated_at"],
        )
        for r in rows
    ]


async def get_task_outputs(task_ids: list[str]) -> dict[str, dict[str, Any]]:
    """Return the latest-retry output payload for each task in *task_ids*.

    Args:
        task_ids: Task UUIDs whose outputs should be loaded.

    Returns:
        Mapping ``task_id -> output dict`` for tasks that exist.  Missing or
        empty outputs are returned as empty dicts.
    """
    if not task_ids:
        return {}

    async with raw_conn(readonly=True) as conn:
        cur = await conn.execute(
            """
            SELECT t.task_id, te.output
            FROM fin_agents.tasks t
            LEFT JOIN LATERAL (
                SELECT output
                FROM fin_agents.task_executions
                WHERE task_id = t.task_id
                ORDER BY retry_num DESC
                LIMIT 1
            ) te ON TRUE
            WHERE t.task_id = ANY(%s)
            """,
            (task_ids,),
        )
        rows = await cur.fetchall()

    return {str(r["task_id"]): (r["output"] or {}) for r in rows}


__all__ = ["get_task_memory", "get_task_outputs"]
