"""SQL query constants for task-level lifecycle operations."""

# Fix 3+5 – fencing_token is added as the 7th positional parameter.
# Params: (task_id, thread_id, node_id, node_name, task_name, input_json,
#          fencing_token)
# ON CONFLICT DO NOTHING because task_id is a UUID4 — duplicates cannot
# occur in normal operation; the guard is a safety net.
_INSERT_TASK = """
    INSERT INTO fin_agents.tasks
        (task_id, thread_id, node_id, node_name, task_name, status, input,
         created_at, updated_at, fencing_token)
    VALUES (%s, %s, %s, %s, %s, 'running', %s::jsonb, NOW(), NOW(), %s)
    ON CONFLICT (task_id) DO NOTHING
"""

_UPDATE_TASK_COMPLETED = """
    UPDATE fin_agents.tasks
    SET status = %s,
        output = %s::jsonb,
        updated_at = NOW()
    WHERE task_id = %s
      AND thread_id = %s
      AND status NOT IN ('completed', 'failed', 'cancelled', 'wrong')
"""

_CANCEL_TASK = """
    UPDATE fin_agents.tasks
    SET status     = 'cancelled',
        output     = '{}'::jsonb,
        updated_at = NOW()
    WHERE task_id = %s
      AND thread_id = %s
      AND status NOT IN ('completed', 'failed', 'cancelled', 'wrong')
    RETURNING task_id, task_name, node_id, node_name
"""

# Fix 3 – Zombie task cleanup: mark all running tasks from the aborted zombie
# run (identified by their fencing_token) as 'wrong'.
# Called by cleanup_zombie_tasks() in the finally block of _run_graph when
# lock_lost_event is set.
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
    "_UPDATE_TASK_COMPLETED",
    "_CANCEL_TASK",
    "_CLEANUP_ZOMBIE_TASKS",
]
