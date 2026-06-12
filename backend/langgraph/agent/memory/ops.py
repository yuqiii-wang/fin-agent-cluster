"""Unified read/write/query API for agent memory entries.

Memory entries are stored in ``fin_agents.agent_memory`` and scoped to a
single ``node_id`` (one run of one graph node).  Two entry flavours exist:

* **Task-backed** — ``task_id`` refers to a row in ``fin_agents.tasks``;
  ``content`` is nullable (the effective content is the referenced task's
  latest ``fin_agents.task_executions.output``).
* **Direct** — ``task_id`` is ``None`` and ``content`` is a non-empty JSONB
  payload stored directly in the memory row.

All lookups are scoped to a single node — there is intentionally no
"cross-node memory" API; state propagation across nodes must go through the
graph's own node inputs/outputs instead.
"""

from __future__ import annotations

import logging
from typing import Any

from backend.db.postgres import raw_conn
from backend.db.postgres.queries.fin_agents import AgentMemorySQL
from backend.langgraph.agent.memory.models import MemoryCheckItem, MemoryItem

logger = logging.getLogger(__name__)


def _row_to_memory_item(row: dict[str, Any]) -> MemoryItem:
    """Build a :class:`MemoryItem` from a raw DB row, resolving effective content."""
    stored_content = row.get("content")
    referenced_output = row.get("task_output")
    task_id = row.get("task_id")
    has_task = task_id is not None

    if has_task and stored_content is None and referenced_output is not None:
        effective_content = referenced_output
    elif stored_content is not None:
        effective_content = stored_content
    elif has_task and referenced_output is not None:
        effective_content = referenced_output
    else:
        effective_content = stored_content

    return MemoryItem(
        memory_id=str(row["memory_id"]),
        thread_id=row["thread_id"],
        node_id=row["node_id"],
        task_id=row.get("task_id"),
        name=row["name"],
        description=row.get("description") or "",
        content=stored_content,
        effective_content=effective_content,
        task_name=row.get("task_name"),
        task_status=row.get("task_status"),
        created_at=row.get("created_at"),
        updated_at=row.get("updated_at"),
    )


async def write_memory(
    thread_id: str,
    node_id: str,
    name: str,
    *,
    description: str = "",
    content: dict[str, Any] | None = None,
    task_id: str | None = None,
) -> str:
    """Write or upsert a memory entry for ``node_id``.

    * If ``task_id`` is set, ``content`` is optional.  When the referenced
      task has output in ``fin_agents.task_executions``, that output becomes
      the effective content at read time.
    * If ``task_id`` is ``None``, ``content`` must be a non-empty JSON-serial
      dict (enforced at the DB level).

    On conflict with an existing ``(node_id, name)`` the row is
    updated in place.

    Args:
        thread_id:   Owning thread UUID.
        node_id:     Owning node UUID — scope of this memory entry.
        name:        Stable logical name for the entry; unique within node_id.
        description: Human-readable description shown in memory listings.
        content:     Optional JSON payload for direct (non-task-backed) memory.
        task_id:     Optional FK to a task row for task-backed memory.

    Returns:
        The UUID (``memory_id``) of the written row.

    Raises:
        ValueError: If both ``task_id`` and ``content`` are unset / empty,
                    because the row would violate the DB CHECK constraint.
    """
    if task_id is None and (content is None or not content):
        raise ValueError(
            "write_memory: when task_id is not set, content must be a "
            "non-empty dict."
        )

    memory_id_arg: str | None = None
    content_arg: dict[str, Any] | None = content if (content and content) else None

    async with raw_conn() as conn:
        cur = await conn.execute(
            AgentMemorySQL.INSERT,
            (
                memory_id_arg,
                thread_id,
                node_id,
                task_id,
                name,
                description,
                content_arg,
            ),
        )
        row = await cur.fetchone()
        return str(row["memory_id"])


async def list_memory(node_id: str) -> list[MemoryItem]:
    """Return every memory entry for ``node_id`` with payloads resolved."""
    async with raw_conn(readonly=True) as conn:
        cur = await conn.execute(AgentMemorySQL.GET_BY_NODE, (node_id,))
        rows = await cur.fetchall()
    return [_row_to_memory_item(dict(r)) for r in rows]


async def get_memory_by_id(memory_id: str) -> MemoryItem | None:
    """Return a single memory entry by its UUID, or ``None`` if not found."""
    async with raw_conn(readonly=True) as conn:
        cur = await conn.execute(AgentMemorySQL.GET_BY_MEMORY_ID, (memory_id,))
        row = await cur.fetchone()
    if row is None:
        return None
    return _row_to_memory_item(dict(row))


async def get_memory_by_name(node_id: str, name: str) -> MemoryItem | None:
    """Return a single memory entry by its stable logical name within a node."""
    async with raw_conn(readonly=True) as conn:
        cur = await conn.execute(AgentMemorySQL.GET_BY_NAME, (node_id, name))
        row = await cur.fetchone()
    if row is None:
        return None
    return _row_to_memory_item(dict(row))


async def check_memory(node_id: str) -> list[MemoryCheckItem]:
    """Lightweight listing of memory entries for ``node_id`` (without payloads).

    Useful for letting an agent (or the UI) see which memory items exist and
    pick one by name before fetching the full payload.
    """
    async with raw_conn(readonly=True) as conn:
        cur = await conn.execute(AgentMemorySQL.CHECK_MEMORY, (node_id,))
        rows = await cur.fetchall()
    return [
        MemoryCheckItem(
            memory_id=str(r["memory_id"]),
            name=r["name"],
            description=r.get("description") or "",
            task_id=r.get("task_id"),
            created_at=r.get("created_at"),
        )
        for r in rows
    ]


async def delete_memory(node_id: str, name: str) -> str | None:
    """Delete a memory entry by name within the given node.

    Returns:
        The deleted ``memory_id``, or ``None`` if no such entry existed.
    """
    async with raw_conn() as conn:
        cur = await conn.execute(
            AgentMemorySQL.DELETE_BY_NAME, (node_id, name)
        )
        row = await cur.fetchone()
    return str(row["memory_id"]) if row else None


__all__ = [
    "write_memory",
    "list_memory",
    "get_memory_by_id",
    "get_memory_by_name",
    "check_memory",
    "delete_memory",
]
