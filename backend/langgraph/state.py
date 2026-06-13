"""Graph state schema for the fin-analysis LangGraph.

Hierarchy
---------
Thread (thread_id)
  └── Node  (node_id = UUID5(thread_id:node_name:v{fork_generation}))
        └── Task  (task_id = UUID4)

State design
------------
GraphState carries only graph topology -- not domain data.  Actual node/task
execution payloads (inputs and outputs) are stored in the separate DB tables
``fin_agents.node_executions`` and ``fin_agents.task_executions``.

This keeps LangGraph checkpoint blobs small and removes the need for nodes
to pass large dicts through the state between steps.

Node identity and fork versioning
----------------------------------
``fork_generation`` is the monotonic branch counter stored in the checkpoint.
  1 = original run
  2 = first re-explore (fork) branch
  n = nth re-explore branch

Every node that runs during a branch uses:
  node_id = UUID5(NAMESPACE, f"{thread_id}:{node_name}:v{fork_generation}")

Nodes that were already checkpointed before the fork point keep their
original ``node_id`` (they don't re-run).  Nodes at and after the fork point
get a new ``node_id`` (new fork_generation value).

``NodeRecord`` shape (also stored in fin_agents.nodes)
-------------------------------------------------------
{
    "node_id":       str,          -- UUID5-derived stable ID
    "task_ids":      list[str],    -- UUID4 task IDs spawned by this node
    "metadata": {                  -- mirrors fin_agents.nodes columns
        "node_name":    str,
        "type":         str,       -- "Workflow" | "Reference" | "Subgraph"
        "status":       str,       -- "running" | "completed" | "failed" | ...
        "version":      int,       -- fork_generation at time of execution
        "checkpoint_id": str,      -- LG checkpoint_id at node start
    },
    "prev_node_ids": list[str],    -- predecessor node IDs in this branch
    "next_node_ids": list[str],    -- successor node IDs (filled on completion)
}
"""

from __future__ import annotations

import operator
from typing import Annotated, Any, Optional
from typing_extensions import TypedDict


class NodeRecord(TypedDict, total=False):
    """Per-node topology record stored in GraphState.nodes."""

    node_id: str
    task_ids: list[str]
    metadata: dict[str, Any]     # node_name, type, status, version, checkpoint_id
    prev_node_ids: list[str]
    next_node_ids: list[str]


class GraphState(TypedDict, total=False):
    # ── Thread-level identity ─────────────────────────────────────────
    thread_id: str
    user_id: str
    query: str

    # ── Fork generation counter ───────────────────────────────────────
    # 0 = original run; incremented by re_explore_node before fork dispatch.
    # All nodes that execute in this branch use this as their version.
    fork_generation: int

    # ── Fork point metadata (set by re_explore_node, cleared after first use) ─
    # Name of the first node to run in this fork branch.  The node whose
    # node_name matches this value marks itself as is_forked=TRUE in the DB.
    fork_point_node_name: Optional[str]
    # Version of the source node being re-explored (the "from" side of the fork).
    fork_source_version: Optional[int]
    # When the re-explored node is part of a parallel group, this holds the
    # group label so sibling nodes can detect they should shortcut (copy v0
    # output to a new v1 DB record without re-running business logic).
    fork_parallel_group: Optional[str]

    # ── Live DAG of node records ──────────────────────────────────────
    # Keyed by node_id (UUID5).  Parallel branches merge via dict-union so
    # concurrent nodes never clobber each other's entries.
    nodes: Annotated[dict[str, NodeRecord], operator.or_]

    # ── Final answer (kept in state for executor.py to pass to complete_thread)
    conclusion: Optional[str]

    # ── Routing hint: UTC query timestamp captured by query_node ─────────────
    # Used by _route_to_region in graph.py to select the regional analyze node.
    # Stored as a plain scalar (not a blob) so it does not inflate checkpoints.
    query_time: str

    # ── Error propagation (any node can set this) ─────────────────────
    error: Optional[str]
