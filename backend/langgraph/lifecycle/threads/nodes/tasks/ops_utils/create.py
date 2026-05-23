"""Task creation lifecycle operation."""

from __future__ import annotations

import json
import logging
import time
from typing import Any

from backend.db.postgres import raw_conn
from backend.langgraph.lifecycle.errors import LIFECYCLE_DB_ERROR
from backend.langgraph.lifecycle.threads.nodes.tasks.sql import (
    _INSERT_TASK,
    _INSERT_TASK_EXECUTION,
)
from backend.langgraph.lifecycle.threads.nodes.tasks.sse import emit_task_sse
from backend.langgraph.models.task import get_task_description

logger = logging.getLogger(__name__)


async def create_task(
    thread_id: str,
    node_id: str,
    node_name: str,
    task_id: str,
    task_name: str,
    input_data: dict[str, Any],
    *,
    view_type: str = "ToolCall",
    stats_views: list[str] | None = None,
) -> None:
    """Persist a new task row and emit a ``task_status: running`` SSE event.

    Writes task metadata to ``fin_agents.tasks`` and execution payload to
    ``fin_agents.task_executions`` in the same connection. Then calls
    ``append_node_task_id`` to record the task_id on the node row.

    The task description is resolved automatically from the global
    ``_TASK_DESCRIPTIONS`` registry populated when ``NodeTask`` instances
    are constructed at import time.

    Args:
        thread_id:    LangGraph thread UUID.
        node_id:      UUID5-derived owning node ID.
        node_name:    Human-readable node name.
        task_id:      Unique task UUID (from ``make_task_id``).
        task_name:    Handler key (e.g. ``"analyze_query"``).
        input_data:   Serialisable input payload for the task.
        view_type:    ``fin_agents.task_view_types`` value (default ``"ToolCall"``).
                      Pass ``"Streaming"`` for LLM streaming tasks.
        stats_views:  Ordered list of applicable stats view type names (Stats tasks only).
                      E.g. ``["DataFrame", "CandleStick"]``.
    """
    from backend.langgraph.lifecycle.threads.nodes.ops import append_node_task_id
    from backend.main_thread.context import get_fencing_token

    description = get_task_description(task_name)
    fencing_token = get_fencing_token()
    views = stats_views or []
    t0 = time.monotonic()
    try:
        async with raw_conn() as conn:
            await conn.execute(
                _INSERT_TASK,
                (task_id, thread_id, node_id, node_name, task_name, description, view_type, views, fencing_token),
            )
            await conn.execute(
                _INSERT_TASK_EXECUTION,
                (task_id, json.dumps(input_data)),
            )
        await append_node_task_id(thread_id, node_id, task_id)
    except Exception as exc:
        logger.error(
            "[%s] create_task DB error task_id=%s thread_id=%s: %s",
            LIFECYCLE_DB_ERROR, task_id, thread_id, exc,
        )
        raise

    logger.debug(
        "[lifecycle:task] created task_id=%s task_name=%s node_name=%s db_ms=%.0f",
        task_id, task_name, node_name, (time.monotonic() - t0) * 1000,
    )
    t_sse = time.monotonic()
    await emit_task_sse(
        thread_id, task_id, task_name, node_id, node_name,
        status="running",
        payload={"input": input_data},
        view_type=view_type,
        stats_views=views,
    )
    logger.debug(
        "[lifecycle:task] running SSE done task_id=%s sse_ms=%.0f",
        task_id, (time.monotonic() - t_sse) * 1000,
    )


__all__ = ["create_task"]
