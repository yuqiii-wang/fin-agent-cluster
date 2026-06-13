"""PostgreSQL layer error code registry.

Error code prefixes
-------------------
``PG_POOL_``          -- Connection pool lifecycle errors.
``PG_CHECKPOINTER_``  -- LangGraph checkpointer setup errors.
``PG_QUERY_``         -- Query execution failures.
"""

from __future__ import annotations

# ---------------------------------------------------------------------------
# Error code constants
# ---------------------------------------------------------------------------

# ── Connection pool ───────────────────────────────────────────────────────────

#: Connection pool accessed before open_pools() was called in FastAPI lifespan.
PG_POOL_NOT_OPENED = "PG_POOL_NOT_OPENED"

# ── Checkpointer setup ────────────────────────────────────────────────────────

#: Checkpointer timed out waiting for the distributed setup lock.
PG_CHECKPOINTER_TIMEOUT = "PG_CHECKPOINTER_TIMEOUT"

#: Checkpointer lock was released but the sentinel key or flag was not set --
#: setup did not complete successfully.
PG_CHECKPOINTER_SETUP_FAILED = "PG_CHECKPOINTER_SETUP_FAILED"

# ── Query execution ───────────────────────────────────────────────────────────

#: A database query function caught an exception and returned None / empty result.
PG_QUERY_FAILED = "PG_QUERY_FAILED"

#: The server terminated the connection mid-query (AdminShutdown / OperationalError).
#: The caller retried and the retry also failed, or this is logged on the first retry attempt.
PG_CONN_TERMINATED = "PG_CONN_TERMINATED"

# ---------------------------------------------------------------------------
# Description registry
# ---------------------------------------------------------------------------

#: Maps each PostgreSQL error code to a human-readable description.
PG_ERRORS: dict[str, str] = {
    PG_POOL_NOT_OPENED: (
        "The PostgreSQL connection pool has not been opened. "
        "Ensure open_pools() is called in the FastAPI lifespan before accepting requests."
    ),
    PG_CHECKPOINTER_TIMEOUT: (
        "The LangGraph checkpointer timed out waiting for the distributed setup lock. "
        "Another instance may be stuck during setup; check Redis lock state."
    ),
    PG_CHECKPOINTER_SETUP_FAILED: (
        "The LangGraph checkpointer setup lock was released but setup did not complete. "
        "Check the backend logs for the root cause."
    ),
    PG_CONN_TERMINATED: (
        "The PostgreSQL server terminated the connection mid-query (AdminShutdown / OperationalError). "
        "The operation was retried; check for frequent occurrences which indicate pool misconfiguration "
        "or recurring server restarts."
    ),
    PG_QUERY_FAILED: (
        "A database query failed and returned no result. "
        "Check the backend logs and verify PostgreSQL connectivity."
    ),
}
