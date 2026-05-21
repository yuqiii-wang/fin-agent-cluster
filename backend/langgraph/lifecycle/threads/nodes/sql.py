"""SQL query constants for node-level lifecycle operations."""

# Params: (node_id, thread_id, version, type, parent_node_id,
#          node_name, checkpoint_id, prev_node_ids, parallel_group, parallel_branch,
#          fencing_token, is_forked, forked_from_version, view_type, view_schema, stats_views)
#
# ON CONFLICT rules:
#   • If the incoming fencing_token is LOWER than stored → zombie write; reject.
#   • If the stored status is already terminal → keep it regardless of token.
#   • Otherwise → overwrite with 'running' and the new prev_node_ids.
#   • fencing_token is always updated to GREATEST(incoming, stored).
#   • is_forked / forked_from_version: once TRUE/set, preserved on conflict.
#   • parallel_branch: once set, preserved on conflict (branch identity is immutable).
_UPSERT_NODE = """
    INSERT INTO fin_agents.nodes
        (node_id, thread_id, version, type, parent_node_id, node_name,
         status, checkpoint_id, prev_node_ids, next_node_ids, task_ids,
         started_at, updated_at, parallel_group, parallel_branch, fencing_token,
         is_forked, forked_from_version, view_type, view_schema, stats_views)
    VALUES (%s, %s, %s, %s, %s, %s, 'running', %s, %s, '{}', '{}', NOW(), NOW(), %s, %s, %s,
            %s, %s, %s::fin_agents.node_view_types, %s::jsonb, %s)
    ON CONFLICT (node_id) DO UPDATE
    SET status              = CASE
                                WHEN excluded.fencing_token < fin_agents.nodes.fencing_token
                                THEN fin_agents.nodes.status
                                WHEN fin_agents.nodes.status IN
                                     ('completed', 'failed', 'cancelled', 'wrong')
                                THEN fin_agents.nodes.status
                                ELSE 'running'
                              END,
        prev_node_ids       = CASE
                                WHEN excluded.fencing_token < fin_agents.nodes.fencing_token
                                THEN fin_agents.nodes.prev_node_ids
                                ELSE EXCLUDED.prev_node_ids
                              END,
        checkpoint_id       = CASE
                                WHEN excluded.fencing_token < fin_agents.nodes.fencing_token
                                THEN fin_agents.nodes.checkpoint_id
                                ELSE EXCLUDED.checkpoint_id
                              END,
        fencing_token       = GREATEST(excluded.fencing_token, fin_agents.nodes.fencing_token),
        is_last_paused_by_server = CASE
                                WHEN excluded.fencing_token < fin_agents.nodes.fencing_token
                                THEN fin_agents.nodes.is_last_paused_by_server
                                WHEN fin_agents.nodes.status IN
                                     ('completed', 'failed', 'cancelled', 'wrong')
                                THEN fin_agents.nodes.is_last_paused_by_server
                                ELSE TRUE
                              END,
        parallel_group      = EXCLUDED.parallel_group,
        parallel_branch     = COALESCE(fin_agents.nodes.parallel_branch, EXCLUDED.parallel_branch),
        is_forked           = CASE
                                WHEN fin_agents.nodes.is_forked THEN TRUE
                                ELSE EXCLUDED.is_forked
                              END,
        forked_from_version = COALESCE(fin_agents.nodes.forked_from_version,
                                       EXCLUDED.forked_from_version),
        updated_at          = NOW()
"""

# Insert the execution payload row (input data) for a node.
# ON CONFLICT updates input so re-starts overwrite stale data.
# Params: (node_id, input_json)
_INSERT_NODE_EXECUTION = """
    INSERT INTO fin_agents.node_executions (node_id, input, updated_at)
    VALUES (%s, %s::jsonb, NOW())
    ON CONFLICT (node_id) DO UPDATE
    SET input      = EXCLUDED.input,
        updated_at = NOW()
"""

# Params: (status, node_id, thread_id, fencing_token)
# Guard: only update if the stored fencing_token matches the caller's token.
_UPDATE_NODE_COMPLETED = """
    UPDATE fin_agents.nodes
    SET status     = %s,
        elapsed_ms = ROUND(EXTRACT(EPOCH FROM (NOW() - started_at)) * 1000)::INT,
        updated_at = NOW()
    WHERE node_id   = %s
      AND thread_id = %s
      AND status NOT IN ('completed', 'failed', 'cancelled', 'wrong')
      AND fencing_token = %s
"""

# Write output payload to node_executions after the node completes.
# Params: (output_json, node_id)
_UPDATE_NODE_EXECUTION_OUTPUT = """
    UPDATE fin_agents.node_executions
    SET output     = %s::jsonb,
        updated_at = NOW()
    WHERE node_id = %s
"""

# Append a task_id to a node's task_ids array.
# Params: (task_id, node_id, thread_id)
_APPEND_NODE_TASK_ID = """
    UPDATE fin_agents.nodes
    SET task_ids   = array_append(task_ids, %s),
        updated_at = NOW()
    WHERE node_id   = %s
      AND thread_id = %s
"""

# Update next_node_ids for a node (set when successor nodes start).
# Params: (next_node_ids, node_id, thread_id)
_UPDATE_NODE_NEXT_IDS = """
    UPDATE fin_agents.nodes
    SET next_node_ids = %s,
        updated_at    = NOW()
    WHERE node_id   = %s
      AND thread_id = %s
"""

_CANCEL_NODE_SELF = """
    UPDATE fin_agents.nodes
    SET status     = 'cancelled',
        updated_at = NOW()
    WHERE node_id  = %s
      AND thread_id = %s
      AND status NOT IN ('completed', 'failed', 'cancelled', 'wrong')
    RETURNING node_id, node_name
"""

# Pause a node when all its tasks are paused (no remaining running tasks).
# is_last_paused_by_server=TRUE for server shutdown, FALSE for user-initiated pause.
# Params: (is_last_paused_by_server, node_id, thread_id, fencing_token)
_PAUSE_NODE = """
    UPDATE fin_agents.nodes
    SET status                   = 'paused',
        is_last_paused_by_server = %s,
        updated_at               = NOW()
    WHERE node_id      = %s
      AND thread_id    = %s
      AND status       = 'running'
      AND fencing_token = %s
    RETURNING node_id, node_name
"""

# Resume a paused node back to running when the user continues its task.
# No fencing token guard since this is called from outside the graph run (API layer).
# Params: (node_id, thread_id)
_RESUME_NODE = """
    UPDATE fin_agents.nodes
    SET status     = 'running',
        updated_at = NOW()
    WHERE node_id   = %s
      AND thread_id = %s
      AND status    = 'paused'
    RETURNING node_id, node_name
"""

_CANCEL_ACTIVE_TASKS_BY_NODE = """
    UPDATE fin_agents.tasks
    SET status     = 'cancelled',
        updated_at = NOW()
    WHERE node_id  = %s
      AND thread_id = %s
      AND status NOT IN ('completed', 'failed', 'cancelled', 'wrong')
    RETURNING task_id, task_name, node_name
"""

# ---------------------------------------------------------------------------
# Parallel-branch cross-snapshot operations
# ---------------------------------------------------------------------------

# Refresh the current node's parallel_snapshots with the latest node_id per
# sibling branch (i.e. every branch in the same parallel_group whose
# parallel_branch differs from ours, taking the most-recently-started node
# per branch).
#
# Params: (thread_id, parallel_group, parent_node_id, parallel_branch, node_id)
_REFRESH_OWN_PARALLEL_SNAPSHOT = """
    UPDATE fin_agents.nodes
    SET parallel_snapshots = (
        SELECT COALESCE(jsonb_object_agg(ranked.parallel_branch, ranked.node_id), '{}')
        FROM (
            SELECT DISTINCT ON (n.parallel_branch) n.parallel_branch, n.node_id
            FROM fin_agents.nodes n
            WHERE n.thread_id = %s
              AND n.parallel_group = %s
              AND n.parent_node_id IS NOT DISTINCT FROM %s
              AND n.parallel_branch != %s
              AND n.parallel_branch IS NOT NULL
            ORDER BY n.parallel_branch, n.started_at DESC
        ) ranked
    ),
    updated_at = NOW()
    WHERE node_id = %s
"""

# When the current node starts it becomes the new "latest" for its branch.
# Propagate its node_id into every sibling node's parallel_snapshots[branch].
# Only overwrites if no snapshot for this branch exists yet, or if the
# previously stored node for this branch started earlier than the current node
# (ensures a later node in the chain always wins).
#
# Params: (parallel_branch, node_id, node_id, parallel_branch, parallel_branch, parallel_branch)
_PROPAGATE_TO_PARALLEL_SIBLINGS = """
    UPDATE fin_agents.nodes AS target
    SET parallel_snapshots = jsonb_set(
            target.parallel_snapshots,
            ARRAY[%s],
            to_jsonb(%s::text)
        ),
        updated_at = NOW()
    FROM fin_agents.nodes AS incoming
    WHERE incoming.node_id = %s
      AND target.thread_id = incoming.thread_id
      AND target.parallel_group = incoming.parallel_group
      AND target.parent_node_id IS NOT DISTINCT FROM incoming.parent_node_id
      AND target.parallel_branch IS NOT NULL
      AND target.parallel_branch != %s
      AND (
          NOT (target.parallel_snapshots ? %s)
          OR NOT EXISTS (
              SELECT 1
              FROM fin_agents.nodes AS older
              WHERE older.node_id = target.parallel_snapshots ->> %s
                AND older.started_at >= incoming.started_at
          )
      )
"""

__all__ = [
    "_UPSERT_NODE",
    "_INSERT_NODE_EXECUTION",
    "_UPDATE_NODE_COMPLETED",
    "_UPDATE_NODE_EXECUTION_OUTPUT",
    "_APPEND_NODE_TASK_ID",
    "_UPDATE_NODE_NEXT_IDS",
    "_CANCEL_NODE_SELF",
    "_PAUSE_NODE",
    "_RESUME_NODE",
    "_CANCEL_ACTIVE_TASKS_BY_NODE",
    "_REFRESH_OWN_PARALLEL_SNAPSHOT",
    "_PROPAGATE_TO_PARALLEL_SIBLINGS",
]
