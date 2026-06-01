"""SQL query constants for thread-level lifecycle operations."""

_UPDATE_THREAD_STATUS = """
    UPDATE fin_agents.user_queries
    SET status = %s
    WHERE thread_id = %s
      AND status NOT IN ('completed', 'failed', 'cancelled', 'wrong')
    RETURNING thread_id
"""

_UPDATE_THREAD_COMPLETED = """
    UPDATE fin_agents.user_queries
    SET status       = %s,
        answer       = %s,
        completed_at = NOW(),
        error        = %s
    WHERE thread_id = %s
      AND status NOT IN ('completed', 'failed', 'cancelled', 'wrong')
    RETURNING thread_id
"""

# Terminal status of the last-ended leaf node (no successors) in the highest
# version.  Used by complete_thread to align the thread status with the final
# end-of-lifecycle node of the latest version (completed | failed | cancelled
# | wrong) instead of assuming 'completed'.
_LATEST_TERMINAL_LEAF_STATUS = """
    SELECT status
    FROM fin_agents.nodes
    WHERE thread_id = %s
      AND status IN ('completed', 'failed', 'cancelled', 'wrong')
      AND cardinality(next_node_ids) = 0
    ORDER BY version DESC, updated_at DESC
    LIMIT 1
"""

# Bulk-cancel all active nodes for the thread (RETURNING for SSE).
_CANCEL_ACTIVE_NODES = """
    UPDATE fin_agents.nodes
    SET status     = 'cancelled',
        updated_at = NOW()
    WHERE thread_id = %s
      AND status NOT IN ('completed', 'failed', 'cancelled', 'wrong')
    RETURNING node_id, node_name
"""

# Bulk-fail any nodes still active when the thread is marked failed.
# Used by complete_thread(failed=True) as a catch-all for nodes whose
# complete_node call was skipped (e.g. fencing-token mismatch on zombie detection).
_FAIL_ACTIVE_NODES = """
    UPDATE fin_agents.nodes
    SET status     = 'failed',
        updated_at = NOW()
    WHERE thread_id = %s
      AND status NOT IN ('completed', 'failed', 'cancelled', 'wrong')
    RETURNING node_id, node_name
"""

# Bulk-cancel all active tasks for the thread (RETURNING task_ids for SSE
# and Celery revocation).
_CANCEL_ACTIVE_TASKS_BY_THREAD = """
    UPDATE fin_agents.tasks
    SET status     = 'cancelled',
        updated_at = NOW()
    WHERE thread_id = %s
      AND status NOT IN ('completed', 'failed', 'cancelled', 'wrong')
    RETURNING task_id
"""

# Fetch thread IDs whose status is not terminal — used during shutdown.
_LIST_ACTIVE_THREAD_IDS = """
    SELECT thread_id
    FROM fin_agents.user_queries
    WHERE status NOT IN ('completed', 'failed', 'cancelled', 'wrong')
"""

__all__ = [
    "_UPDATE_THREAD_STATUS",
    "_UPDATE_THREAD_COMPLETED",
    "_LATEST_TERMINAL_LEAF_STATUS",
    "_CANCEL_ACTIVE_NODES",
    "_FAIL_ACTIVE_NODES",
    "_CANCEL_ACTIVE_TASKS_BY_THREAD",
    "_LIST_ACTIVE_THREAD_IDS",
]
