"""Bridge between NodeTask definitions and agent ToolInfo metadata.

NodeTask is the canonical task definition (input schema, description, Celery
dispatch, LangGraph @task).  This module is the bridge layer that converts
NodeTask objects into the lightweight ToolInfo representation used by:

- ``capabilities.py`` -- capability selection and system-prompt building.
- ``loop.py`` -- resolving which StructuredTools to bind to the LLM.
- ``api/`` -- displaying tool metadata to the UI.
"""

from __future__ import annotations

from typing import Any

from backend.db.postgres import raw_conn
from backend.langgraph.agent.tools.models import ToolInfo


def get_tool_infos_for_tasks(tasks: list[Any]) -> list[ToolInfo]:
    """Build ToolInfo metadata from a list of NodeTask objects.

    This is the primary bridge entry point: NodeTask carries the full
    implementation details (Pydantic input model, async coroutine, Celery
    handler); ToolInfo is the serialisable projection used for context
    building and LLM capability selection.

    Args:
        tasks: List of :class:`~backend.langgraph.models.task.NodeTask`
               instances taken directly from a ``BaseNode.tasks`` registry.

    Returns:
        Ordered list of :class:`ToolInfo`, one per task, preserving registry
        order.
    """
    return [
        ToolInfo(
            name=t.name,
            description=t.description,
            input_schema=t.input_type.model_json_schema(),
        )
        for t in tasks
    ]


async def get_tools_for_node(node_id: str) -> list[ToolInfo]:
    """Return ToolInfo metadata for *node_id* from the node class registry.

    Resolves ``node_name`` from ``fin_agents.nodes``, looks up the
    ``BaseNode`` instance in ``NODE_REGISTRY``, and delegates to
    :func:`get_tool_infos_for_tasks` for the full schema/description data.

    Falls back to reading distinct task names from ``fin_agents.tasks``
    (empty description/schema) when the node is not in the registry.

    Args:
        node_id: Agent node UUID.

    Returns:
        List of :class:`ToolInfo` ordered by task registry position.
    """
    from backend.langgraph.nodes import NODE_REGISTRY

    async with raw_conn(readonly=True) as conn:
        cur = await conn.execute(
            "SELECT node_name FROM fin_agents.nodes WHERE node_id = %s LIMIT 1",
            (node_id,),
        )
        row = await cur.fetchone()

    if row:
        node_instance = NODE_REGISTRY.get(row["node_name"])
        if node_instance is not None and hasattr(node_instance, "tasks"):
            return get_tool_infos_for_tasks(node_instance.tasks)

    async with raw_conn(readonly=True) as conn:
        cur = await conn.execute(
            """
            SELECT DISTINCT ON (task_name) task_name, created_at
            FROM fin_agents.tasks
            WHERE node_id = %s
            ORDER BY task_name, created_at
            """,
            (node_id,),
        )
        rows = await cur.fetchall()

    return [
        ToolInfo(name=r["task_name"], description="", input_schema={})
        for r in rows
    ]
