"""SQL query constants for task-level lifecycle operations."""

# Params: (task_id, thread_id, node_id, node_name, task_name, fencing_token)
# ON CONFLICT DO NOTHING because task_id is a UUID4 — duplicates cannot
# occur in normal operation; the guard is a safety net.
_INSERT_TASK = """
    INSERT INTO fin_agents.tasks
        (task_id, thread_id, node_id, node_name, task_name, status,
         created_at, updated_at, fencing_token)
    VALUES (%s, %s, %s, %s, %s, 'running', NOW(), NOW(), %s)
    ON CONFLICT (task_id) DO NOTHING
"""

# Insert the execution payload row (input data) for a task.
# ON CONFLICT updates input so re-starts overwrite stale data.
# Params: (task_id, input_json)
_INSERT_TASK_EXECUTION = """
    INSERT INTO fin_agents.task_executions (task_id, input, updated_at)
    VALUES (%s, %s::jsonb, NOW())
    ON CONFLICT (task_id) DO UPDATE
    SET input      = EXCLUDED.input,
        updated_at = NOW()
"""

# Update task status on completion/failure (no output in this table).
# Params: (status, task_id, thread_id)
_UPDATE_TASK_COMPLETED = """
    UPDATE fin_agents.tasks
    SET status     = %s,
        updated_at = NOW()
    WHERE task_id   = %s
      AND thread_id = %s
      AND status NOT IN ('completed', 'failed', 'cancelled', 'wrong')
"""

# Write output payload to task_executions after the task completes.
# Params: (output_json, task_id)
_UPDATE_TASK_EXECUTION_OUTPUT = """
    UPDATE fin_agents.task_executions
    SET output     = %s::jsonb,
        updated_at = NOW()
    WHERE task_id = %s
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

# Zombie task cleanup: mark all running tasks from the aborted zombie
# run (identified by their fencing_token) as 'wrong'.
# Params: (thread_id, fencing_token)
_CLEANUP_ZOMBIE_TASKS = """
    UPDATE fin_agents.tasks
    SET status     = 'wrong',
        updated_at = NOW()
    WHERE thread_id    = %s
      AND fencing_token = %s
      AND status NOT IN ('completed', 'failed', 'cancelled', 'wrong')
    RETURNING task_id
"""

__all__ = [
    "_INSERT_TASK",
    "_INSERT_TASK_EXECUTION",
    "_UPDATE_TASK_COMPLETED",
    "_UPDATE_TASK_EXECUTION_OUTPUT",
    "_CANCEL_TASK",
    "_CLEANUP_ZOMBIE_TASKS",
]
