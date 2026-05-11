"""SQL query constants for node-level lifecycle operations."""

# Fix 5 – fencing_token is added as the 8th positional parameter.
# Params: (node_id, thread_id, type, parent_node_id, node_name, input_json,
#          parallel_group, fencing_token)
#
# ON CONFLICT rules:
#   • If the incoming fencing_token is LOWER than the stored one → zombie write;
#     preserve the stored status and input (reject the zombie's update).
#   • If the stored status is already terminal → keep it regardless of token.
#   • Otherwise → overwrite with 'running' and the new input.
#   • fencing_token is always updated to GREATEST(incoming, stored) so the
#     column always reflects the highest-generation write.
_UPSERT_NODE = """
    INSERT INTO fin_agents.nodes
        (node_id, thread_id, type, parent_node_id, node_name,
         status, input, started_at, updated_at, parallel_group, fencing_token)
    VALUES (%s, %s, %s, %s, %s, 'running', %s::jsonb, NOW(), NOW(), %s, %s)
    ON CONFLICT (node_id) DO UPDATE
    SET status         = CASE
                           WHEN excluded.fencing_token < fin_agents.nodes.fencing_token
                           THEN fin_agents.nodes.status
                           WHEN fin_agents.nodes.status IN
                                ('completed', 'failed', 'cancelled', 'wrong')
                           THEN fin_agents.nodes.status
                           ELSE 'running'
                         END,
        input          = CASE
                           WHEN excluded.fencing_token < fin_agents.nodes.fencing_token
                           THEN fin_agents.nodes.input
                           ELSE EXCLUDED.input
                         END,
        fencing_token  = GREATEST(excluded.fencing_token, fin_agents.nodes.fencing_token),
        parallel_group = EXCLUDED.parallel_group,
        updated_at     = NOW()
"""

# Fix 5 – params: (status, output_json, node_id, thread_id, fencing_token)
# Guard: only update if the stored fencing_token matches the caller's token.
# A zombie write (lower token than what the real owner upserted) will find
# fencing_token ≠ its own token and produce 0 updated rows → treated as
# "already terminal" and skipped safely.
_UPDATE_NODE_COMPLETED = """
    UPDATE fin_agents.nodes
    SET status     = %s,
        output     = %s::jsonb,
        elapsed_ms = EXTRACT(EPOCH FROM (NOW() - started_at))::INT * 1000,
        updated_at = NOW()
    WHERE node_id  = %s
      AND thread_id = %s
      AND status NOT IN ('completed', 'failed', 'cancelled', 'wrong')
      AND fencing_token = %s
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

_CANCEL_ACTIVE_TASKS_BY_NODE = """
    UPDATE fin_agents.tasks
    SET status     = 'cancelled',
        updated_at = NOW()
    WHERE node_id  = %s
      AND thread_id = %s
      AND status NOT IN ('completed', 'failed', 'cancelled', 'wrong')
    RETURNING task_id, task_name, node_name
"""

__all__ = [
    "_UPSERT_NODE",
    "_UPDATE_NODE_COMPLETED",
    "_CANCEL_NODE_SELF",
    "_CANCEL_ACTIVE_TASKS_BY_NODE",
]
