"""SQL query strings and static sets for the users.queries package."""

from __future__ import annotations

# ---------------------------------------------------------------------------
# SQL
# ---------------------------------------------------------------------------

_INSERT_QUERY_IMMEDIATE = """
    INSERT INTO fin_agents.user_queries
        (thread_id, user_id, query, status, is_ack)
    VALUES (%s, %s, %s, 'received', TRUE)
    RETURNING thread_id, status, query, created_at, completed_at, answer, error
"""

_SET_STATUS_RUNNING = """
    UPDATE fin_agents.user_queries
    SET status = 'running'
    WHERE thread_id = %s
      AND status = 'received'
"""

_SELECT_QUERY = """
    SELECT thread_id, status, query, answer, error, created_at, completed_at
    FROM fin_agents.user_queries
    WHERE thread_id = %s
"""

_ACK_QUERY = """
    UPDATE fin_agents.user_queries
    SET status = 'running', is_ack = TRUE
    WHERE thread_id = %s
      AND status NOT IN ('completed', 'failed', 'cancelled')
    RETURNING thread_id, status, query, answer, error, created_at, completed_at
"""

_CANCEL_QUERY_STATUS = """
    SELECT status FROM fin_agents.user_queries WHERE thread_id = %s
"""

_LIST_NODES = """
    SELECT n.node_id, n.thread_id, n.node_name, n.status, n.type,
           n.parent_node_id, n.parallel_group,
           n.version, n.checkpoint_id, n.prev_node_ids, n.next_node_ids, n.task_ids,
           n.is_forked, n.forked_from_version, n.view_type, n.view_schema,
           ne.input, ne.output,
           n.started_at, n.elapsed_ms, n.updated_at
    FROM fin_agents.nodes n
    LEFT JOIN fin_agents.node_executions ne ON ne.node_id = n.node_id
    WHERE n.thread_id = %s
    ORDER BY n.started_at
"""

_GET_VERSION_FORK_NODE = """
    SELECT n.node_id, n.thread_id, n.node_name, n.status, n.type,
           n.parent_node_id, n.parallel_group,
           n.version, n.checkpoint_id, n.prev_node_ids, n.next_node_ids, n.task_ids,
           n.is_forked, n.forked_from_version, n.view_type, n.view_schema,
           ne.input, ne.output,
           n.started_at, n.elapsed_ms, n.updated_at
    FROM fin_agents.nodes n
    LEFT JOIN fin_agents.node_executions ne ON ne.node_id = n.node_id
    WHERE n.thread_id = %s
      AND n.version   = %s
      AND n.is_forked = TRUE
    LIMIT 1
"""

# Fetch all nodes that belong to a given fork-generation AND any cross-version
# predecessor nodes reachable by following prev_node_ids recursively.
# This ensures that when a re-explore reuses sibling nodes from an earlier version
# (via the parallel shortcut), those shared nodes still appear in the version graph.
#
# Params: (thread_id, version, thread_id, thread_id)
_LIST_NODES_BY_VERSION = """
    WITH RECURSIVE reachable(node_id, prev_node_ids) AS (
        -- Seed: nodes explicitly in this fork generation.
        SELECT n.node_id, n.prev_node_ids
        FROM fin_agents.nodes n
        WHERE n.thread_id = %s AND n.version = %s
        UNION
        -- Expand: follow prev_node_ids to pull in shared predecessors from
        -- earlier versions (e.g. sibling nodes reused via shortcut path).
        SELECT n.node_id, n.prev_node_ids
        FROM fin_agents.nodes n
        INNER JOIN reachable r ON n.node_id = ANY(r.prev_node_ids)
        WHERE n.thread_id = %s
    )
    SELECT n.node_id, n.thread_id, n.node_name, n.status, n.type,
           n.parent_node_id, n.parallel_group,
           n.version, n.checkpoint_id, n.prev_node_ids, n.next_node_ids, n.task_ids,
           n.is_forked, n.forked_from_version, n.view_type, n.view_schema,
           ne.input, ne.output,
           n.started_at, n.elapsed_ms, n.updated_at
    FROM fin_agents.nodes n
    INNER JOIN reachable ON reachable.node_id = n.node_id
    LEFT JOIN fin_agents.node_executions ne ON ne.node_id = n.node_id
    WHERE n.thread_id = %s
    ORDER BY n.started_at
"""

_LIST_TASKS = """
    SELECT t.task_id, t.thread_id, t.node_id, t.node_name, t.task_name,
           t.view_type, t.status, te.input, te.output, t.created_at, t.updated_at
    FROM fin_agents.tasks t
    LEFT JOIN LATERAL (
        SELECT input, output
        FROM fin_agents.task_executions
        WHERE task_id = t.task_id
        ORDER BY retry_num DESC
        LIMIT 1
    ) te ON TRUE
    WHERE t.thread_id = %s
    ORDER BY t.created_at
"""

_ACTIVE_TASK_COUNT_IN_NODE = """
    SELECT COUNT(*) AS cnt
    FROM fin_agents.tasks
    WHERE node_id   = %s
      AND thread_id = %s
      AND status NOT IN ('completed', 'failed', 'cancelled', 'wrong')
"""

_ACTIVE_SIBLING_NODE_COUNT = """
    SELECT COUNT(*) AS cnt
    FROM fin_agents.nodes
    WHERE parent_node_id = %s
      AND thread_id      = %s
      AND status NOT IN ('completed', 'failed', 'cancelled', 'wrong')
"""

_ACTIVE_TOP_LEVEL_NODE_COUNT = """
    SELECT COUNT(*) AS cnt
    FROM fin_agents.nodes
    WHERE thread_id      = %s
      AND parent_node_id IS NULL
      AND status NOT IN ('completed', 'failed', 'cancelled', 'wrong')
"""

__all__ = [
    "_INSERT_QUERY_IMMEDIATE",
    "_SET_STATUS_RUNNING",
    "_SELECT_QUERY",
    "_ACK_QUERY",
    "_CANCEL_QUERY_STATUS",
    "_LIST_NODES",
    "_GET_VERSION_FORK_NODE",
    "_LIST_NODES_BY_VERSION",
    "_LIST_TASKS",
    "_ACTIVE_TASK_COUNT_IN_NODE",
    "_ACTIVE_SIBLING_NODE_COUNT",
    "_ACTIVE_TOP_LEVEL_NODE_COUNT",
]
