"""backend.langgraph.lifecycle.threads.nodes — node-level lifecycle.

Public API
----------
:func:`upsert_node`         — INSERT or UPDATE a node row; emit ``node_status: running``.
:func:`complete_node`       — UPDATE to completed/failed; emit ``node_status: completed``.
:func:`pause_node`          — UPDATE to paused; set is_last_paused_by_server; emit SSE.
:func:`resume_node`         — UPDATE from paused to running; emit ``node_status: running``.
:func:`cancel_node`         — UPDATE to cancelled; cascade to all active tasks; emit SSE.
:func:`read_node_output`    — Read completed node output from PG replica.
:func:`append_node_task_id` — Append a task_id to the node's task_ids array.

Implementation split
--------------------
sql.py  — SQL query constants
ops.py  — public API implementations
sse.py  — internal SSE helper functions
"""

from backend.langgraph.lifecycle.threads.nodes.ops import (
    append_node_task_id,
    cancel_node,
    complete_node,
    get_latest_sibling_node_version,
    pause_node,
    resume_node,
    read_node_output,
    upsert_node,
)

__all__ = ["upsert_node", "complete_node", "pause_node", "resume_node", "cancel_node", "get_latest_sibling_node_version", "read_node_output", "append_node_task_id"]
