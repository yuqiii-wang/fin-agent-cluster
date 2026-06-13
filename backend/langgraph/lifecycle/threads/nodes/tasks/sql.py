"""SQL query constants for task-level lifecycle operations."""

# Params: (task_id, thread_id, node_id, node_name, task_name, description, view_type, stats_views, fencing_token, cache_ttl_seconds)
# ON CONFLICT DO NOTHING because task_id is a UUID4 -- duplicates cannot
# occur in normal operation; the guard is a safety net.
_INSERT_TASK = """
    INSERT INTO fin_agents.tasks
        (task_id, thread_id, node_id, node_name, task_name, description, view_type, stats_views,
         status, created_at, updated_at, fencing_token, cache_ttl_seconds)
    VALUES (%s, %s, %s, %s, %s, %s, %s::fin_agents.task_view_types, %s, 'running', NOW(), NOW(), %s, %s)
    ON CONFLICT (task_id) DO NOTHING
"""

# Insert the initial execution payload row (retry_num = 0) for a new task.
# ON CONFLICT is a safety net: task_id is UUID4 so duplicates cannot occur normally.
# Params: (task_id, input_json)
_INSERT_TASK_EXECUTION = """
    INSERT INTO fin_agents.task_executions (task_id, retry_num, input, updated_at)
    VALUES (%s, 0, %s::jsonb, NOW())
    ON CONFLICT (task_id, retry_num) DO UPDATE
    SET input      = EXCLUDED.input,
        updated_at = NOW()
"""

# Update task status on completion/failure.
# cache_ttl_seconds is set to the configured value on success, 0 on failure --
# so only healthily completed tasks are eligible for cache reuse.
# Params: (status, cache_ttl_seconds, task_id, thread_id)
_UPDATE_TASK_COMPLETED = """
    UPDATE fin_agents.tasks
    SET status            = %s,
        cache_ttl_seconds = %s,
        updated_at        = NOW()
    WHERE task_id   = %s
      AND thread_id = %s
      AND status NOT IN ('completed', 'failed', 'cancelled', 'wrong', 'paused')
"""

# Write output payload to the latest retry row of task_executions after the task completes.
# Params: (output_json, task_id, task_id)
_UPDATE_TASK_EXECUTION_OUTPUT = """
    UPDATE fin_agents.task_executions
    SET output     = %s::jsonb,
        updated_at = NOW()
    WHERE task_id  = %s
      AND retry_num = (SELECT MAX(retry_num) FROM fin_agents.task_executions WHERE task_id = %s)
"""

_CANCEL_TASK = """
    UPDATE fin_agents.tasks
    SET status     = 'cancelled',
        updated_at = NOW()
    WHERE task_id   = %s
      AND thread_id = %s
      AND status NOT IN ('completed', 'failed', 'cancelled', 'wrong')
    RETURNING task_id, task_name, node_id, node_name
"""

# Pause a specific task: worker is no longer running but the task is retryable.
# Node stays in 'running' state (no cascade).
# Params: (task_id, thread_id)
_PAUSE_TASK = """
    UPDATE fin_agents.tasks
    SET status     = 'paused',
        updated_at = NOW()
    WHERE task_id   = %s
      AND thread_id = %s
      AND status NOT IN ('completed', 'failed', 'cancelled', 'wrong', 'paused')
    RETURNING task_id, task_name, node_id, node_name
"""

# Zombie task cleanup: mark all running tasks from the aborted zombie
# run (identified by their fencing_token) as 'wrong'.
# Params: (thread_id, fencing_token)
_CLEANUP_ZOMBIE_TASKS = """
    UPDATE fin_agents.tasks
    SET status     = 'wrong',
        updated_at = NOW()
    WHERE thread_id    = %s
      AND fencing_token = %s
      AND status NOT IN ('completed', 'failed', 'cancelled', 'wrong', 'paused')
    RETURNING task_id
"""

# Reset a terminal task back to 'running' for retry.
# Only transitions from completed/failed/cancelled/paused -- guards against double-reset.
# Params: (task_id, thread_id)
_RESET_TASK_FOR_RETRY = """
    UPDATE fin_agents.tasks
    SET status     = 'running',
        updated_at = NOW()
    WHERE task_id   = %s
      AND thread_id = %s
      AND status IN ('completed', 'failed', 'cancelled', 'paused')
    RETURNING task_id, task_name, node_id, node_name, view_type, stats_views
"""

# Insert a new execution row for a retried task (retry_num = prev_max + 1).
# Copies input from the most recent retry row; output starts empty.
# Params: (task_id,)
_INSERT_RETRY_TASK_EXECUTION = """
    WITH prev AS (
        SELECT task_id, retry_num, input
        FROM fin_agents.task_executions
        WHERE task_id = %s
        ORDER BY retry_num DESC
        LIMIT 1
    )
    INSERT INTO fin_agents.task_executions (task_id, retry_num, input, updated_at)
    SELECT task_id, retry_num + 1, input, NOW()
    FROM prev
"""

# Fetch a single task with its execution payload (input/output) from the latest retry.
# Params: (task_id, thread_id)
_GET_TASK_FULL = """
    SELECT t.task_id, t.thread_id, t.node_id, t.node_name, t.task_name,
           t.view_type, t.stats_views, t.status, te.input, te.output,
           t.created_at, t.updated_at
    FROM fin_agents.tasks t
    LEFT JOIN LATERAL (
        SELECT input, output
        FROM fin_agents.task_executions
        WHERE task_id = t.task_id
        ORDER BY retry_num DESC
        LIMIT 1
    ) te ON TRUE
    WHERE t.task_id = %s AND t.thread_id = %s
"""

# Fetch the latest LLM response (thinking + answer) for a task.
# Used by compact_and_continue to obtain prior thinking text.
# Params: (task_id,)
_GET_LATEST_LLM_RESPONSE = """
    SELECT thinking, answer
    FROM fin_agents.llm_responses
    WHERE task_id = %s
    ORDER BY ts DESC
    LIMIT 1
"""

# Find a paused task for a specific node+task_name.
# Called by node.run_task on graph resume to detect whether to continue from snapshot.
# Params: (thread_id, node_id, task_name)
_GET_PAUSED_TASK_FOR_NODE = """
    SELECT task_id
    FROM fin_agents.tasks
    WHERE thread_id = %s
      AND node_id    = %s
      AND task_name  = %s
      AND status     = 'paused'
    LIMIT 1
"""

# Called by node.run_task to detect any existing task for (node_id, task_name).
# For non-completed statuses the match is unconditional so paused/failed tasks
# are reused (task_id reuse for retry). For completed tasks the input_hash must
# match the current invocation AND the task must still be within its cache TTL.
# Params: (thread_id, node_id, task_name, input_json)
_GET_EXISTING_TASK_FOR_NODE = """
    SELECT t.task_id, t.status, t.updated_at, t.cache_ttl_seconds
    FROM fin_agents.tasks t
    LEFT JOIN fin_agents.task_executions te
        ON te.task_id = t.task_id AND te.retry_num = 0
    WHERE t.thread_id = %s
      AND t.node_id    = %s
      AND t.task_name  = %s
      AND (
          t.status != 'completed'
          OR (
              te.input_hash = md5(%s::jsonb::text)
              AND t.updated_at > NOW() - (t.cache_ttl_seconds * INTERVAL '1 second')
          )
      )
    LIMIT 1
"""

# Return the node_name for a given node_id.
# Params: (node_id,)
_GET_NODE_NAME_BY_ID = """
    SELECT node_name
    FROM fin_agents.nodes
    WHERE node_id = %s
    LIMIT 1
"""

# Zero-out cache_ttl_seconds for all completed tasks that share the same
# node_name as the given node_id, across all versions under the thread.
# Called by the invalidate-cache API endpoint.
# Params: (thread_id, node_id)
_INVALIDATE_NODE_TASK_CACHES = """
    UPDATE fin_agents.tasks
    SET cache_ttl_seconds = 0,
        updated_at        = NOW()
    WHERE thread_id = %s
      AND node_name = (
          SELECT node_name
          FROM fin_agents.nodes
          WHERE node_id = %s
          LIMIT 1
      )
      AND status    = 'completed'
"""

# Bulk-pause all running tasks on graceful shutdown.
# Nodes intentionally stay 'running' so recover_running_threads re-runs them
# on restart and node.run_task detects the paused task for compact_and_continue.
_BULK_PAUSE_RUNNING_TASKS = """
    UPDATE fin_agents.tasks
    SET status     = 'paused',
        updated_at = NOW()
    WHERE status = 'running'
    RETURNING task_id, thread_id
"""

__all__ = [
    "_INSERT_TASK",
    "_INSERT_TASK_EXECUTION",
    "_UPDATE_TASK_COMPLETED",
    "_UPDATE_TASK_EXECUTION_OUTPUT",
    "_CANCEL_TASK",
    "_CLEANUP_ZOMBIE_TASKS",
    "_RESET_TASK_FOR_RETRY",
    "_INSERT_RETRY_TASK_EXECUTION",
    "_GET_TASK_FULL",
    "_GET_LATEST_LLM_RESPONSE",
    "_GET_PAUSED_TASK_FOR_NODE",
    "_GET_EXISTING_TASK_FOR_NODE",
    "_GET_NODE_NAME_BY_ID",
    "_INVALIDATE_NODE_TASK_CACHES",
    "_BULK_PAUSE_RUNNING_TASKS",
]
