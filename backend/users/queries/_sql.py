"""backend.users.queries._sql — Raw SQL constants for user query operations."""

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
           n.is_forked, n.forked_from_version, n.view_type, n.view_schema, n.stats_views,
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
           n.is_forked, n.forked_from_version, n.view_type, n.view_schema, n.stats_views,
           ne.input, ne.output,
           n.started_at, n.elapsed_ms, n.updated_at
    FROM fin_agents.nodes n
    LEFT JOIN fin_agents.node_executions ne ON ne.node_id = n.node_id
    WHERE n.thread_id = %s
      AND n.version   = %s
      AND n.is_forked = TRUE
    LIMIT 1
"""

_LIST_NODES_BY_VERSION = """
    WITH v_nodes AS (
        SELECT n.node_id, n.thread_id, n.node_name, n.status, n.type,
               n.parent_node_id, n.parallel_group,
               n.version, n.checkpoint_id, n.prev_node_ids, n.next_node_ids, n.task_ids,
               n.is_forked, n.forked_from_version, n.view_type, n.view_schema, n.stats_views,
               ne.input, ne.output,
               n.started_at, n.elapsed_ms, n.updated_at
        FROM fin_agents.nodes n
        LEFT JOIN fin_agents.node_executions ne ON ne.node_id = n.node_id
        WHERE n.thread_id = %s AND n.version = %s
    ),
    shared_ids AS (
        SELECT DISTINCT unnest(prev_node_ids) AS node_id FROM v_nodes
    ),
    shared_nodes AS (
        SELECT n.node_id, n.thread_id, n.node_name, n.status, n.type,
               n.parent_node_id, n.parallel_group,
               n.version, n.checkpoint_id, n.prev_node_ids, n.next_node_ids, n.task_ids,
               n.is_forked, n.forked_from_version, n.view_type, n.view_schema, n.stats_views,
               ne.input, ne.output,
               n.started_at, n.elapsed_ms, n.updated_at
        FROM fin_agents.nodes n
        LEFT JOIN fin_agents.node_executions ne ON ne.node_id = n.node_id
        JOIN shared_ids s ON n.node_id = s.node_id
        WHERE n.node_id NOT IN (SELECT node_id FROM v_nodes)
          AND n.parallel_group IN (
              SELECT DISTINCT parallel_group FROM v_nodes WHERE parallel_group IS NOT NULL
          )
    )
    SELECT * FROM v_nodes
    UNION ALL
    SELECT * FROM shared_nodes
    ORDER BY started_at
"""

_LIST_TASKS = """
    SELECT t.task_id, t.thread_id, t.node_id, t.node_name, t.task_name,
           t.view_type, t.stats_views, t.status, te.input, te.output, t.created_at, t.updated_at
    FROM fin_agents.tasks t
    LEFT JOIN fin_agents.task_executions te ON te.task_id = t.task_id
    WHERE t.thread_id = %s
    ORDER BY t.created_at
"""

_GET_TASK_BY_ID = """
    SELECT t.task_id, t.thread_id, t.node_id, t.node_name, t.task_name,
           t.view_type, t.stats_views, t.status, te.input, te.output, t.created_at, t.updated_at
    FROM fin_agents.tasks t
    LEFT JOIN fin_agents.task_executions te ON te.task_id = t.task_id
    WHERE t.thread_id = %s AND t.task_id = %s
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
    "_GET_TASK_BY_ID",
    "_ACTIVE_TASK_COUNT_IN_NODE",
    "_ACTIVE_SIBLING_NODE_COUNT",
    "_ACTIVE_TOP_LEVEL_NODE_COUNT",
]
