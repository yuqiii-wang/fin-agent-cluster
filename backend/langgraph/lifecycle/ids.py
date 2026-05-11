"""Stable ID generators for the lifecycle hierarchy.

Node IDs are **deterministic**: the same (thread_id, node_name) pair always
produces the same string.  This guarantees that multiple invocations of the
same node within a thread (e.g. on retry) resolve to the same DB row.

Task IDs are **unique** (UUID4) — each @task invocation gets a fresh ID.
"""

from __future__ import annotations

import uuid


def make_node_id(thread_id: str, node_name: str) -> str:
    """Return a stable node identifier for the given thread + node name.

    The format ``{thread_id}:{node_name}`` is human-readable and guaranteed
    unique within a thread because node names are unique within a graph.

    Args:
        thread_id: LangGraph thread UUID.
        node_name: Registered node name (e.g. ``"query_node"``).

    Returns:
        Deterministic string ID stored in ``fin_agents.nodes.node_id``.
    """
    return f"{thread_id}:{node_name}"


def make_task_id() -> str:
    """Generate a unique task UUID for a single @task invocation.

    Returns:
        Fresh UUID4 string stored in ``fin_agents.tasks.task_id``.
    """
    return str(uuid.uuid4())


__all__ = ["make_node_id", "make_task_id"]
