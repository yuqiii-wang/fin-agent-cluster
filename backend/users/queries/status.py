"""backend.users.queries.status — Read-only query/node/task status helpers."""

from __future__ import annotations

from typing import Any

from backend.db.postgres import raw_conn
from backend.users.schemas import (
    NodeExecutionInfo,
    QueryResponse,
    SessionStatus,
    TaskInfo,
    VersionGraphResponse,
)
from backend.users.queries._sql import (
    _SELECT_QUERY,
    _LIST_NODES,
    _GET_VERSION_FORK_NODE,
    _LIST_NODES_BY_VERSION,
    _LIST_TASKS,
    _GET_TASK_BY_ID,
)
from backend.users.queries._helpers import _row_to_query_response, _row_to_node_info, _get_topology_safe


async def get_query_status(thread_id: str) -> QueryResponse:
    """Return the current status of a query thread from the DB.

    Args:
        thread_id: LangGraph thread UUID.

    Returns:
        :class:`QueryResponse` reflecting the latest DB state.
    """
    async with raw_conn(readonly=True) as conn:
        cur = await conn.execute(_SELECT_QUERY, (thread_id,))
        row = await cur.fetchone()
    if row is None:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail=f"Thread {thread_id} not found")
    return _row_to_query_response(row)


async def get_node_executions(thread_id: str) -> list[NodeExecutionInfo]:
    """Return all node executions for a thread ordered by start time.

    Args:
        thread_id: LangGraph thread UUID.

    Returns:
        List of :class:`NodeExecutionInfo` records.
    """
    async with raw_conn(readonly=True) as conn:
        cur = await conn.execute(_LIST_NODES, (thread_id,))
        rows = await cur.fetchall()
    return [_row_to_node_info(r) for r in rows]


async def get_version_graph(thread_id: str, version: int) -> VersionGraphResponse:
    """Return the fork node and all nodes for a given version.

    For version 0 (original run): ``fork_node`` is ``None``, ``source_version`` is ``None``.
    For version V > 0: ``fork_node`` is the ``is_forked=TRUE`` node that started the
    new branch, ``source_version`` is ``fork_node.forked_from_version``, and
    ``nodes`` lists all nodes that executed under version V.

    Args:
        thread_id: LangGraph thread UUID.
        version:   Fork generation to fetch (0 = original run).

    Returns:
        :class:`VersionGraphResponse` for the requested version.
    """
    from fastapi import HTTPException

    async with raw_conn(readonly=True) as conn:
        if version > 0:
            cur = await conn.execute(_GET_VERSION_FORK_NODE, (thread_id, version))
            fork_row = await cur.fetchone()
        else:
            fork_row = None

        cur = await conn.execute(_LIST_NODES_BY_VERSION, (thread_id, version, thread_id, thread_id))
        node_rows = await cur.fetchall()

    if version > 0 and fork_row is None and not node_rows:
        raise HTTPException(
            status_code=404,
            detail=f"Version {version} not found for thread {thread_id}",
        )

    fork_node = _row_to_node_info(fork_row) if fork_row else None
    source_version: int | None = fork_row["forked_from_version"] if fork_row else None

    executed_nodes = [_row_to_node_info(r) for r in node_rows]
    pending_nodes = _build_pending_frontier(thread_id, version, node_rows)

    return VersionGraphResponse(
        version=version,
        thread_id=thread_id,
        fork_node=fork_node,
        source_version=source_version,
        nodes=executed_nodes + pending_nodes,
    )


def _build_pending_frontier(
    thread_id: str,
    version: int,
    node_rows: list[Any],
) -> list[NodeExecutionInfo]:
    """Return +1 depth pending NodeExecutionInfo entries for a version graph.

    Inspects the compiled graph topology to find nodes whose ALL predecessors
    have run in this version but which have not started yet.  These are
    returned as ``status='pending'`` entries (rendered grey in the UI) so the
    version graph shows the complete expected topology, not just what ran.

    Returns an empty list when the topology is unavailable or the frontier
    is empty (all nodes ran, or next nodes lead to END).

    Args:
        thread_id: LangGraph thread UUID.
        version:   Fork generation being queried.
        node_rows: Raw DB rows from ``_LIST_NODES_BY_VERSION``.

    Returns:
        List of :class:`NodeExecutionInfo` with ``status='pending'``.
    """
    topo = _get_topology_safe()
    if topo is None:
        return []

    # Build ran-node map: node_name → node_id, keeping the highest-version row.
    ran_node_id: dict[str, str] = {}
    ran_node_ver: dict[str, int] = {}
    ran_node_names: set[str] = set()
    for r in node_rows:
        name: str = r["node_name"]
        v: int = r["version"] or 0
        ran_node_names.add(name)
        if v >= ran_node_ver.get(name, -1):
            ran_node_ver[name] = v
            ran_node_id[name] = r["node_id"]

    # Predecessor map: to_node → [from_node, ...] built from topology edges.
    pred_map: dict[str, list[str]] = {}
    for edge in topo.edges:
        pred_map.setdefault(edge.to_node, []).append(edge.from_node)

    pending: list[NodeExecutionInfo] = []
    for topo_node in topo.nodes:
        name = topo_node.node_name
        if name in ran_node_names:
            continue
        preds = pred_map.get(name, [])
        if not preds:
            continue  # root node — would have already run if reachable
        if all(p in ran_node_names for p in preds):
            prev_ids = [ran_node_id[p] for p in preds if p in ran_node_id]
            pending.append(NodeExecutionInfo(
                node_id=f"topology-{name}",
                thread_id=thread_id,
                node_name=name,
                status="pending",
                type=topo_node.node_type,
                parallel_group=topo_node.parallel_group,
                version=version,
                prev_node_ids=prev_ids,
            ))

    return pending


async def get_query_tasks(thread_id: str) -> SessionStatus:
    """Return the query record and all its agent sub-tasks.

    Args:
        thread_id: LangGraph thread UUID.

    Returns:
        :class:`SessionStatus` with the thread and all tasks.
    """
    thread = await get_query_status(thread_id)

    async with raw_conn(readonly=True) as conn:
        cur = await conn.execute(_LIST_TASKS, (thread_id,))
        rows = await cur.fetchall()

    tasks = [_build_task_info(r) for r in rows]
    return SessionStatus(thread=thread, tasks=tasks)


def _build_task_info(r: Any) -> TaskInfo:
    """Convert a DB row to :class:`TaskInfo`, enriching completed streaming tasks.

    For streaming tasks that have completed, overrides ``view_type`` to ``"Hybrid"``
    and sets ``view_schema`` so the frontend renders thinking as Markdown and
    the answer as Json.

    Args:
        r: A psycopg3 row mapping with the columns from ``_LIST_TASKS`` / ``_GET_TASK_BY_ID``.

    Returns:
        :class:`TaskInfo` with proper view metadata.
    """
    view_type: str = r["view_type"] or "ToolCall"
    stats_views: list[str] = list(r["stats_views"]) if r["stats_views"] else []
    is_streaming: bool = view_type == "Streaming"
    view_schema: dict | None = None

    if is_streaming and r["status"] == "completed" and r["output"]:
        view_type = "Hybrid"
        view_schema = {"thinking": "Markdown", "answer": "Json"}

    return TaskInfo(
        task_id=r["task_id"],
        thread_id=r["thread_id"],
        node_id=r["node_id"],
        node_name=r["node_name"],
        task_name=r["task_name"],
        status=r["status"],
        view_type=view_type,
        stats_views=stats_views,
        is_streaming=is_streaming,
        view_schema=view_schema,
        input=r["input"],
        output=r["output"],
        created_at=r["created_at"],
        updated_at=r["updated_at"],
    )


async def get_task_by_id(thread_id: str, task_id: str) -> TaskInfo:
    """Fetch a single task by its UUID, enriching completed streaming tasks.

    Args:
        thread_id: LangGraph thread UUID (scoping guard).
        task_id:   Task execution UUID.

    Returns:
        :class:`TaskInfo` for the task.

    Raises:
        HTTPException 404: If the task is not found under this thread.
    """
    from fastapi import HTTPException

    async with raw_conn(readonly=True) as conn:
        cur = await conn.execute(_GET_TASK_BY_ID, (thread_id, task_id))
        row = await cur.fetchone()

    if row is None:
        raise HTTPException(status_code=404, detail=f"Task {task_id} not found in thread {thread_id}")

    return _build_task_info(row)


__all__ = [
    "get_query_status",
    "get_node_executions",
    "get_version_graph",
    "get_query_tasks",
    "get_task_by_id",
]
