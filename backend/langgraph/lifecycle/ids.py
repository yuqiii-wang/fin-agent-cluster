"""Stable ID generators for the lifecycle hierarchy.

Node IDs are **deterministic** via UUID5: the same (thread_id, node_name,
version) triple always produces the same UUID string.  This guarantees that
nodes within a branch are consistently identified and that different fork
versions of the same logical node produce distinct IDs.

Task IDs are **unique** (UUID4) — each @task invocation gets a fresh ID.

Fork versioning
---------------
``fork_generation`` is stored in ``GraphState`` and starts at 1 for the
original run.  Re-exploring (forking) a node increments it to 2, 3, … so
that every node executed in the new branch gets a distinct ``node_id`` from
all prior branches, while nodes that were already checkpointed before the
fork point keep their original IDs (they do not re-execute).
"""

from __future__ import annotations

import re
import uuid

_SUFFIX_RE = re.compile(r"_(node|subgraph)$")


def strip_node_suffix(name: str) -> str:
    """Strip trailing ``_node`` or ``_subgraph`` from a node name for UI display.

    Args:
        name: Raw registered node name (e.g. ``"query_node"``).

    Returns:
        Display name without the trailing type suffix (e.g. ``"query"``).
    """
    return _SUFFIX_RE.sub("", name)

# UUID5 namespace (URL namespace — arbitrary but stable across processes).
_NODE_NAMESPACE = uuid.UUID("6ba7b810-9dad-11d1-80b4-00c04fd430c8")


def make_node_id(thread_id: str, node_name: str, version: int = 1) -> str:
    """Return a UUID5-derived stable node identifier.

    The deterministic formula ``UUID5(NS, "{thread_id}:{node_name}:v{version}")``
    guarantees:
    - Same result for the same (thread, name, version) across all processes.
    - Different result for different fork versions of the same logical node.

    Args:
        thread_id: LangGraph thread UUID.
        node_name: Registered node name (e.g. ``"query_node"``).
        version:   Fork generation counter; 1 = original run, 2+ = fork branch.

    Returns:
        UUID5 string stored in ``fin_agents.nodes.node_id``.
    """
    return str(uuid.uuid5(_NODE_NAMESPACE, f"{thread_id}:{node_name}:v{version}"))


def make_task_id() -> str:
    """Generate a unique task UUID for a single @task invocation.

    Returns:
        Fresh UUID4 string stored in ``fin_agents.tasks.task_id``.
    """
    return str(uuid.uuid4())


async def get_next_fork_generation(thread_id: str) -> int:
    """Return the next fork_generation for a thread.

    Queries the maximum ``version`` stored across all nodes for this thread
    and returns ``max_version + 1``.  For a thread with no prior forks this
    returns ``1`` (original run = 0, first fork = 1).

    This is an async function because it reads from the DB.

    Args:
        thread_id: LangGraph thread UUID.

    Returns:
        New fork_generation integer to store in ``GraphState.fork_generation``
        before dispatching the fork run.
    """
    from backend.db.postgres import raw_conn

    async with raw_conn(readonly=True) as conn:
        cur = await conn.execute(
            "SELECT COALESCE(MAX(version), 0) AS max_ver "
            "FROM fin_agents.nodes WHERE thread_id = %s",
            (thread_id,),
        )
        row = await cur.fetchone()
    return (row["max_ver"] if row else 0) + 1


__all__ = ["make_node_id", "make_task_id", "get_next_fork_generation", "strip_node_suffix"]
