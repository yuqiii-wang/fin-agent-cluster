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

    LIST_ACTIVE_THREAD_IDS = """
        SELECT thread_id
        FROM fin_agents.user_queries
        WHERE status NOT IN ('completed', 'failed', 'cancelled')
    """


class NodeSQL:
    """Queries against ``fin_agents.nodes``."""

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
        ORDER BY started_at
    """

    UPSERT = """
        INSERT INTO fin_agents.nodes
            (node_id, thread_id, type, parent_node_id, node_name,
             status, input, started_at, updated_at)
        VALUES (%s, %s, %s, %s, %s, 'running', %s::jsonb, NOW(), NOW())
        ON CONFLICT (node_id) DO UPDATE
        SET status     = CASE
                           WHEN fin_agents.nodes.status IN
                                ('completed', 'failed', 'cancelled', 'wrong')
                           THEN fin_agents.nodes.status
                           ELSE 'running'
                         END,
            input      = EXCLUDED.input,
            updated_at = NOW()
    """

    UPDATE_STATUS = """
        UPDATE fin_agents.nodes
        SET status     = %s,
            updated_at = NOW()
        WHERE node_id  = %s
          AND thread_id = %s
          AND status NOT IN ('completed', 'failed', 'cancelled', 'wrong')
    """

    UPDATE_COMPLETED = """
        UPDATE fin_agents.nodes
        SET status     = %s,
            output     = %s::jsonb,
            elapsed_ms = ROUND(EXTRACT(EPOCH FROM (NOW() - started_at)) * 1000)::INT,
            updated_at = NOW()
        WHERE node_id  = %s
          AND thread_id = %s
          AND status NOT IN ('completed', 'failed', 'cancelled', 'wrong')
    """

    LIST_ACTIVE_BY_THREAD = """
        SELECT node_id, node_name, status
        FROM fin_agents.nodes
        WHERE thread_id = %s
          AND status NOT IN ('completed', 'failed', 'cancelled', 'wrong')
    """

    CANCEL_ALL_ACTIVE_BY_THREAD = """
        UPDATE fin_agents.nodes
        SET status     = 'cancelled',
            updated_at = NOW()
        WHERE thread_id = %s
          AND status NOT IN ('completed', 'failed', 'cancelled', 'wrong')
        RETURNING node_id, node_name
    """

    CANCEL_BY_ID = """
        UPDATE fin_agents.nodes
        SET status     = 'cancelled',
            updated_at = NOW()
        WHERE node_id  = %s
          AND thread_id = %s
          AND status NOT IN ('completed', 'failed', 'cancelled', 'wrong')
        RETURNING node_id, node_name
    """

    GET_THREAD_BY_NODE_ID = """
        SELECT thread_id
        FROM fin_agents.nodes
        WHERE node_id = %s
        LIMIT 1
    """


class TaskSQL:
    """Queries against ``fin_agents.tasks``."""

    INSERT = """
        INSERT INTO fin_agents.tasks
            (task_id, thread_id, node_id, node_name, task_name, status, input,
             created_at, updated_at)
        VALUES (%s, %s, %s, %s, %s, 'running', %s::jsonb, NOW(), NOW())
        ON CONFLICT (task_id) DO NOTHING
    """

    UPDATE_COMPLETED = """
        UPDATE fin_agents.tasks
        SET status     = %s,
            output     = %s::jsonb,
            updated_at = NOW()
        WHERE task_id  = %s
          AND thread_id = %s
          AND status NOT IN ('completed', 'failed', 'cancelled', 'wrong')
    """

    CANCEL_BY_ID = """
        UPDATE fin_agents.tasks
        SET status     = 'cancelled',
            updated_at = NOW()
        WHERE task_id  = %s
          AND thread_id = %s
          AND status NOT IN ('completed', 'failed', 'cancelled', 'wrong')
        RETURNING task_id
    """

    CANCEL_ALL_ACTIVE_BY_NODE = """
        UPDATE fin_agents.tasks
        SET status     = 'cancelled',
            updated_at = NOW()
        WHERE node_id  = %s
          AND thread_id = %s
          AND status NOT IN ('completed', 'failed', 'cancelled', 'wrong')
        RETURNING task_id
    """

    CANCEL_ALL_ACTIVE_BY_THREAD = """
        UPDATE fin_agents.tasks
        SET status     = 'cancelled',
            updated_at = NOW()
        WHERE thread_id = %s
          AND status NOT IN ('completed', 'failed', 'cancelled', 'wrong')
        RETURNING task_id
    """

    ALL_TASKS_TERMINAL_FOR_NODE = """
        SELECT NOT EXISTS (
            SELECT 1
            FROM fin_agents.tasks
            WHERE node_id  = %s
              AND thread_id = %s
              AND status NOT IN ('completed', 'failed', 'cancelled', 'wrong')
        ) AS all_terminal
    """

    LIST_ACTIVE_BY_NODE = """
        SELECT task_id, status
        FROM fin_agents.tasks
        WHERE node_id  = %s
          AND thread_id = %s
          AND status NOT IN ('completed', 'failed', 'cancelled', 'wrong')
    """

    LIST_BY_THREAD = """
        SELECT
            t.task_id,
            t.thread_id,
            t.node_id,
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
            t.task_id,
            t.thread_id,
            t.node_id,
            t.node_name,
            t.task_name,
            t.status,
            t.input,
            t.output,
            t.created_at,
            t.updated_at
        FROM fin_agents.tasks t
        WHERE t.task_id = ANY(%s)
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
        SELECT task_id
        FROM fin_agents.tasks
        WHERE thread_id = %s
          AND node_name = %s
        ORDER BY created_at
    """

    GET_THREAD_BY_TASK_ID = """
        SELECT thread_id
        FROM fin_agents.tasks
        WHERE task_id = %s
        LIMIT 1
    """
