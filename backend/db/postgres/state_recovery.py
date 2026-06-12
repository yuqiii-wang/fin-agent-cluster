"""State recovery from Postgres DB for LangGraph checkpoints.

Recovers node and task data from fin_agents.nodes and fin_agents.tasks
tables to reconstruct GraphState when node IDs change (e.g., after a fork).
"""

import logging
from typing import Any, Dict, List, Optional, Type, TypeVar

from psycopg import AsyncConnection
from psycopg.rows import dict_row
from pydantic import BaseModel

from backend.db.postgres.connection import raw_conn
from backend.db.postgres.queries.fin_agents import NodeSQL, TaskSQL
from backend.langgraph.state import GraphState, NodeRecord
from backend.langgraph.models.models import TaskRecord, TaskOutput, TaskContext, NodeContext

logger = logging.getLogger(__name__)

T = TypeVar('T', bound=BaseModel)


async def recover_graph_state_from_db(
    thread_id: str,
    current_nodes: Dict[str, NodeRecord]
) -> Dict[str, NodeRecord]:
    """Recover node/task data from Postgres DB for a given thread.

    Args:
        thread_id: The thread ID to recover state for
        current_nodes: Current nodes dict from GraphState (may have new node IDs)

    Returns:
        Updated nodes dict with data recovered from DB for matching node names
    """
    recovered_nodes: Dict[str, NodeRecord] = {}

    async with raw_conn(readonly=True) as conn:
        # First get all nodes from DB for this thread
        cur = await conn.execute(NodeSQL.LIST_BY_THREAD, (thread_id,))
        db_nodes = await cur.fetchall()

        # Create a map from node_name to list of DB node records (ordered by started_at)
        db_node_map: Dict[str, List[Dict[str, Any]]] = {}
        for db_node in db_nodes:
            node_name = db_node["node_name"]
            if node_name not in db_node_map:
                db_node_map[node_name] = []
            db_node_map[node_name].append(db_node)

        # Now process each current node and recover from DB if possible
        for current_node_id, current_node in current_nodes.items():
            node_name = current_node.get("metadata", {}).get("node_name")
            if not node_name:
                recovered_nodes[current_node_id] = current_node
                continue

            # Find matching DB nodes with this node_name
            if node_name not in db_node_map:
                recovered_nodes[current_node_id] = current_node
                continue

            # Use the latest DB node for this node_name
            latest_db_node = db_node_map[node_name][-1]

            # Get all tasks for this DB node
            cur = await conn.execute(
                TaskSQL.GET_IDS_BY_NODE,
                (thread_id, node_name)
            )
            db_task_ids = [row["task_id"] for row in await cur.fetchall()]

            # Build recovered NodeRecord
            recovered_node: NodeRecord = {
                "node_id": current_node_id,
                "task_ids": db_task_ids,
                "metadata": {
                    "node_name": node_name,
                    "type": latest_db_node.get("type", "Workflow"),
                    "status": latest_db_node.get("status", "running"),
                    "version": current_node.get("metadata", {}).get("version", 1),
                    "checkpoint_id": latest_db_node.get("checkpoint_id"),
                },
                "prev_node_ids": current_node.get("prev_node_ids", []),
                "next_node_ids": current_node.get("next_node_ids", []),
            }

            recovered_nodes[current_node_id] = recovered_node

    return recovered_nodes


async def get_node_data_from_db(
    thread_id: str,
    node_id: str
) -> Optional[Dict[str, Any]]:
    """Get single node's data from Postgres DB.

    Args:
        thread_id: Thread ID
        node_id: Node ID to fetch

    Returns:
        Node data dict from DB, or None if not found
    """
    async with raw_conn(readonly=True) as conn:
        cur = await conn.execute(NodeSQL.GET_BY_ID, (node_id, thread_id))
        return await cur.fetchone()


async def get_task_data_from_db(
    thread_id: str,
    task_id: str
) -> Optional[Dict[str, Any]]:
    """Get single task's data from Postgres DB.

    Args:
        thread_id: Thread ID
        task_id: Task ID to fetch

    Returns:
        Task data dict from DB, or None if not found
    """
    async with raw_conn(readonly=True) as conn:
        cur = await conn.execute(
            """
            SELECT *
            FROM fin_agents.tasks
            WHERE task_id = %s AND thread_id = %s
            LIMIT 1
            """,
            (task_id, thread_id)
        )
        return await cur.fetchone()


async def recover_task_output_from_db(
    task_record: TaskRecord,
    output_type: Type[T]
) -> Optional[TaskOutput[T]]:
    """Recover full TaskOutput from Postgres using TaskRecord.

    Args:
        task_record: Lightweight record with thread/node/task IDs
        output_type: Pydantic model type for the task's content

    Returns:
        Full TaskOutput with data from DB, or None if not found
    """
    task_data = await get_task_data_from_db(task_record.thread_id, task_record.task_id)
    if not task_data:
        return None

    # Build NodeContext first
    node_ctx = NodeContext(
        thread_id=task_record.thread_id,
        node_id=task_record.node_id,
        node_name=task_data.get("node_name", ""),
        version=task_data.get("version", 1),
        prev_node_ids=[],
        task_ids=[task_record.task_id],
        metadata={}
    )

    # Build TaskContext
    task_ctx = TaskContext(
        **node_ctx.model_dump(),
        task_id=task_record.task_id,
        task_name=task_data.get("task_name", "")
    )

    # Parse output content
    output_data = task_data.get("output")
    content = None
    if output_data:
        # Streaming tasks store output wrapped in {"thinking": ..., "answer": {...}}
        raw = output_data.get("answer", output_data) if isinstance(output_data.get("answer"), dict) else output_data
        content = output_type.model_validate(raw)

    # Get thinking if available
    thinking = output_data.get("thinking") if isinstance(output_data, dict) else None

    return TaskOutput(
        ctx=task_ctx,
        content=content,
        thinking=thinking
    )


__all__ = [
    "recover_graph_state_from_db",
    "get_node_data_from_db",
    "get_task_data_from_db",
    "recover_task_output_from_db",
]
