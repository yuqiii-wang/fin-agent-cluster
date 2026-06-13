"""backend.users.queries.re_explore -- re_explore_node handler."""

from __future__ import annotations

import logging

from langgraph.errors import InvalidUpdateError

from backend.db.postgres import raw_conn
from backend.users.schemas import QueryResponse
from backend.users.queries.status import get_query_status

logger = logging.getLogger(__name__)


async def re_explore_node(
    thread_id: str,
    node_id: str,
    *,
    input_override: dict | None = None,
) -> QueryResponse:
    """Re-explore a node by forking the graph at the checkpoint just before it ran.

    Finds the LangGraph snapshot where the node_name (or its parent subgraph)
    is in ``snapshot.next``, increments ``fork_generation`` via
    ``graph.aupdate_state`` so all nodes in the new branch get new UUID5
    node_ids, then dispatches the fork run.

    For inner subgraph nodes (``parent_node_id`` is set in the DB), falls back
    to the snapshot where the parent subgraph is in ``next``.

    For topology-only conditional nodes (``node_id`` starts with ``"topology-"``)
    the node has never run -- it was bypassed by the routing decision.  In this
    case the function forks from the checkpoint just before the routing source
    node ran, so the routing decision can be made again.

    Also injects ``fork_point_node_name`` (the callable entry node) and
    ``fork_source_version`` (the version of the re-explored node) into the
    forked checkpoint so the first node can mark itself as ``is_forked=TRUE``.

    Args:
        thread_id:      LangGraph thread UUID.
        node_id:        UUID5-derived node ID (from DB) or ``topology-{node_name}``
                        for conditional nodes that have not yet run.
        input_override: Optional mapping of GraphState field names to new values.

    Returns:
        Updated :class:`QueryResponse` with ``status='running'``.
    """
    from fastapi import HTTPException
    from backend.langgraph.compiled import get_compiled_graph
    from backend.langgraph.lifecycle.ids import get_next_fork_generation
    from backend.langgraph.lifecycle.errors import (
        LIFECYCLE_CHECKPOINT_NOT_FOUND,
        LIFECYCLE_NODE_NOT_FOUND,
    )

    is_topology_only: bool = node_id.startswith("topology-")
    if is_topology_only:
        from backend.api.graph.topology import GRAPH_TOPOLOGY
        raw_node_name = node_id[len("topology-"):]
        cond_edges = [
            e for e in GRAPH_TOPOLOGY.edges
            if e.to_node == raw_node_name and e.kind == "conditional"
        ]
        if not cond_edges:
            logger.error(
                "[%s] re_explore_node: no conditional edges for topology node node_id=%s thread_id=%s",
                LIFECYCLE_CHECKPOINT_NOT_FOUND, node_id, thread_id,
            )
            raise HTTPException(
                status_code=404,
                detail=f"No conditional edge found for topology node '{raw_node_name}'",
            )
        routing_source: str = cond_edges[0].from_node
        node_name: str = raw_node_name
        source_version: int = 0
        parent_node_id: str | None = None
        parent_node_name: str | None = None
        fork_checkpoint_id: str = ""
        fork_point_name: str = routing_source
        pg: str | None = None
    else:
        async with raw_conn(readonly=True) as conn:
            cur = await conn.execute(
                """
                SELECT n.node_name, n.version AS source_version,
                       n.parent_node_id,
                       n.checkpoint_id,
                       n.parallel_group,
                       p.node_name AS parent_node_name,
                       p.checkpoint_id AS parent_checkpoint_id
                FROM fin_agents.nodes n
                LEFT JOIN fin_agents.nodes p
                       ON p.node_id = n.parent_node_id
                      AND p.thread_id = n.thread_id
                WHERE n.node_id = %s AND n.thread_id = %s
                """,
                (node_id, thread_id),
            )
            row = await cur.fetchone()

        if row is None:
            logger.error(
                "[%s] re_explore_node: node not found node_id=%s thread_id=%s",
                LIFECYCLE_NODE_NOT_FOUND, node_id, thread_id,
            )
            raise HTTPException(status_code=404, detail=f"Node {node_id} not found")

        node_name = row["node_name"]
        source_version = row["source_version"] or 0
        parent_node_id = row["parent_node_id"]
        parent_node_name = row["parent_node_name"]
        node_checkpoint_id: str = row["checkpoint_id"] or ""
        parent_checkpoint_id: str = row["parent_checkpoint_id"] or ""
        fork_checkpoint_id = parent_checkpoint_id if parent_node_id else node_checkpoint_id
        fork_point_name = node_name
        routing_source = node_name
        pg = row["parallel_group"]

    graph = get_compiled_graph()
    config = {"configurable": {"thread_id": thread_id}}

    target_snapshot = None
    async for snapshot in graph.aget_state_history(config):
        snap_cid = snapshot.config.get("configurable", {}).get("checkpoint_id", "")
        if not is_topology_only and fork_checkpoint_id and snap_cid == fork_checkpoint_id:
            fork_point_name = parent_node_name if parent_node_id else node_name
            target_snapshot = snapshot
            break
        if not fork_checkpoint_id:
            if is_topology_only:
                if routing_source in snapshot.next:
                    target_snapshot = snapshot
                    break
            else:
                if node_name in snapshot.next:
                    fork_point_name = node_name
                    target_snapshot = snapshot
                    break
                if parent_node_name and parent_node_name in snapshot.next:
                    fork_point_name = parent_node_name
                    target_snapshot = snapshot
                    break

    if target_snapshot is None:
        logger.error(
            "[%s] re_explore_node: no checkpoint found node_id=%s thread_id=%s",
            LIFECYCLE_CHECKPOINT_NOT_FOUND, node_id, thread_id,
        )
        raise HTTPException(
            status_code=404,
            detail=f"No checkpoint found to re-explore node '{node_name}'",
        )

    snap_conf = target_snapshot.config.get("configurable", {})
    fork_configurable: dict = {"thread_id": thread_id}
    if snap_conf.get("checkpoint_id"):
        fork_configurable["checkpoint_id"] = snap_conf["checkpoint_id"]
    if snap_conf.get("checkpoint_ns"):
        fork_configurable["checkpoint_ns"] = snap_conf["checkpoint_ns"]
    fork_config = {"configurable": fork_configurable}

    # If parallel_group was NULL in DB (nodes created before parallel_group
    # class vars were set), fall back to the topology as the canonical source.
    if not pg and not is_topology_only:
        from backend.api.graph.topology import GRAPH_TOPOLOGY
        for _topo_node in GRAPH_TOPOLOGY.nodes:
            if _topo_node.node_name == node_name and _topo_node.parallel_group:
                pg = _topo_node.parallel_group
                break

    new_generation = await get_next_fork_generation(thread_id)
    state_update: dict = {
        "fork_generation": new_generation,
        "fork_point_node_name": fork_point_name,
        "fork_source_version": source_version,
    }
    if pg:
        state_update["fork_parallel_group"] = pg

    # Refresh checkpoint: pre-populate sibling NodeRecords so the forked
    # checkpoint carries each sibling at its furthest completed version.
    # This means subsequent re-explores fork from a checkpoint that already
    # has the correct sibling states, without relying solely on the shortcut
    # path in entrypoint.py.  Siblings with no completed version are skipped
    # (they will run fresh via the normal path).
    if pg and not is_topology_only:
        from backend.api.graph.topology import GRAPH_TOPOLOGY
        from backend.langgraph.lifecycle.ids import make_node_id as _make_node_id
        from backend.langgraph.lifecycle.threads.nodes import get_latest_sibling_node_version

        sibling_nodes: dict = {}
        for _topo_node in GRAPH_TOPOLOGY.nodes:
            if _topo_node.parallel_group != pg or _topo_node.node_name == node_name:
                continue
            sibling_version = await get_latest_sibling_node_version(
                thread_id, _topo_node.node_name
            )
            if sibling_version is None:
                continue
            sibling_node_id = _make_node_id(thread_id, _topo_node.node_name, sibling_version)
            sibling_nodes[sibling_node_id] = {
                "node_id": sibling_node_id,
                "task_ids": [],
                "metadata": {
                    "node_name": _topo_node.node_name,
                    "type": _topo_node.node_type,
                    "status": "completed",
                    "version": sibling_version,
                },
                "prev_node_ids": [],
                "next_node_ids": [],
            }
        if sibling_nodes:
            state_update["nodes"] = sibling_nodes

    if input_override:
        state_update.update(input_override)

    # Use as_node=None so LangGraph infers the predecessor from versions_seen,
    # which keeps fork_point_name in `next` and lets ainvoke actually run it.
    # Using as_node=fork_point_name would mark the fork-point as "already run",
    # moving `next` past it and skipping its Python code entirely.
    #
    # For fan-in nodes (e.g. conclusion_node where both parallel predecessors
    # ran at the same step), LangGraph raises "Ambiguous update" because
    # versions_seen has two nodes at the same channel version.  In that case
    # we pick one direct predecessor from the graph topology.
    try:
        updated_config = await graph.aupdate_state(fork_config, state_update)
    except InvalidUpdateError as e:
        if "Ambiguous" not in str(e):
            raise
        # Build predecessor map from compiled graph topology
        _edges = graph.get_graph().edges
        _predecessors = [
            edge.source
            for edge in _edges
            if edge.target == fork_point_name
            and edge.source not in ("__start__", "__end__")
        ]
        if not _predecessors:
            raise
        updated_config = await graph.aupdate_state(
            fork_config, state_update, as_node=_predecessors[0]
        )

    async with raw_conn() as conn:
        await conn.execute(
            "UPDATE fin_agents.user_queries SET status = 'running'"
            " WHERE thread_id = %s",
            (thread_id,),
        )

    from backend.main_thread import dispatch_graph_run
    import json as _json
    await dispatch_graph_run(
        thread_id,
        f"__fork__:{_json.dumps(updated_config)}",
    )
    status = await get_query_status(thread_id)
    return QueryResponse(**status.model_dump(exclude={"fork_version"}), fork_version=new_generation)


__all__ = ["re_explore_node"]
