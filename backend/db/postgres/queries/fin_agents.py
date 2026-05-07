"""SQL templates for the ``fin_agents`` schema.

All constants are raw SQL strings ready for use with psycopg3 ``%s``
parameterisation.  SQLAlchemy-ORM operations are handled through
``app.models``; these templates cover cases that need raw SQL.
"""


class UserQuerySQL:
    """Queries against ``fin_agents.user_queries``."""

    GET_BY_THREAD = """
        SELECT *
        FROM fin_agents.user_queries
        WHERE thread_id = %s
        LIMIT 1
    """

    INSERT = """
        INSERT INTO fin_agents.user_queries (thread_id, user_id, query, status, extra)
        VALUES (%s, %s, %s, %s, %s::jsonb)
        RETURNING id, thread_id, created_at
    """

    UPDATE_STATUS = """
        UPDATE fin_agents.user_queries
        SET status = %s
        WHERE thread_id = %s
    """

    UPDATE_COMPLETED = """
        UPDATE fin_agents.user_queries
        SET status = %s, answer = %s, completed_at = NOW(), error = %s
        WHERE thread_id = %s
    """

    LIST_BY_USER = """
        SELECT *
        FROM fin_agents.user_queries
        WHERE user_id = %s
        ORDER BY created_at DESC
        LIMIT %s OFFSET %s
    """


class NodeExecutionSQL:
    """Queries against ``fin_agents.node_executions``."""

    INSERT = """
        INSERT INTO fin_agents.node_executions
            (thread_id, node_name, node_uuid, parent_node_execution_id, input, output, started_at, elapsed_ms)
        VALUES (%s, %s, %s, %s, %s::jsonb, %s::jsonb, %s, %s)
    """

    LIST_BY_THREAD = """
        SELECT *
        FROM fin_agents.node_executions
        WHERE thread_id = %s
        ORDER BY started_at
    """


class NodeSQL:
    """Queries against ``fin_agents.nodes`` (per-thread node identity registry)."""

    GET_BY_ID = """
        SELECT *
        FROM fin_agents.nodes
        WHERE node_id = %s
          AND thread_id = %s
        LIMIT 1
    """

    LIST_BY_THREAD = """
        SELECT *
        FROM fin_agents.nodes
        WHERE thread_id = %s
        ORDER BY created_at
    """

    RESOLVE_REFERENCE = """
        WITH RECURSIVE ref_chain AS (
            SELECT node_id, thread_id, node_name, type, referenced_node_id,
                   last_status, last_node_execution_id, last_executed_at,
                   created_at, updated_at,
                   0 AS depth
            FROM fin_agents.nodes
            WHERE node_id = %s
              AND thread_id = %s
            UNION ALL
            SELECT n.node_id, n.thread_id, n.node_name, n.type, n.referenced_node_id,
                   n.last_status, n.last_node_execution_id, n.last_executed_at,
                   n.created_at, n.updated_at,
                   rc.depth + 1
            FROM fin_agents.nodes n
            JOIN ref_chain rc ON n.node_id = rc.referenced_node_id
                              AND n.thread_id = rc.thread_id
                              AND rc.type = 'Reference'
                              AND rc.depth < 10
        )
        SELECT * FROM ref_chain
        WHERE type != 'Reference'
        ORDER BY depth
        LIMIT 1
    """


class TaskSQL:
    """Queries against ``fin_agents.tasks``."""

    LIST_BY_THREAD = """
        SELECT
            t.id,
            t.thread_id,
            t.node_execution_id,
            t.node_name,
            t.task_name,
            t.status,
            t.input,
            t.output,
            t.created_at,
            t.updated_at
        FROM fin_agents.tasks t
        WHERE t.thread_id = %s
        ORDER BY t.created_at
    """

    GET_BY_IDS = """
        SELECT
            t.id,
            t.thread_id,
            t.node_execution_id,
            t.node_name,
            t.task_name,
            t.status,
            t.input,
            t.output,
            t.created_at,
            t.updated_at
        FROM fin_agents.tasks t
        WHERE t.id = ANY(%s::bigint[])
        ORDER BY t.created_at
    """

    COUNT_BY_STATUS = """
        SELECT status, COUNT(*) AS cnt
        FROM fin_agents.tasks
        WHERE thread_id = %s
        GROUP BY status
    """

    HAS_INCOMPLETE = """
        SELECT EXISTS (
            SELECT 1
            FROM fin_agents.tasks
            WHERE thread_id = %s
              AND status NOT IN ('completed', 'failed')
        ) AS has_incomplete
    """

    GET_IDS_BY_NODE = """
        SELECT id
        FROM fin_agents.tasks
        WHERE thread_id = %s
          AND node_name = %s
        ORDER BY id
    """
