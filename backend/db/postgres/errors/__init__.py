"""PostgreSQL layer error code registry package.

Re-exports all error code constants and the ``PG_ERRORS`` description dict::

    from backend.db.postgres.errors import (
        PG_ERRORS,
        PG_POOL_NOT_OPENED,
        PG_CHECKPOINTER_TIMEOUT,
        PG_CHECKPOINTER_SETUP_FAILED,
        PG_QUERY_FAILED,
    )
"""

from __future__ import annotations

from backend.db.postgres.errors.codes import (
    PG_ERRORS,
    PG_POOL_NOT_OPENED,
    PG_CHECKPOINTER_TIMEOUT,
    PG_CHECKPOINTER_SETUP_FAILED,
    PG_QUERY_FAILED,
    PG_CONN_TERMINATED,
)

__all__ = [
    "PG_ERRORS",
    "PG_POOL_NOT_OPENED",
    "PG_CHECKPOINTER_TIMEOUT",
    "PG_CHECKPOINTER_SETUP_FAILED",
    "PG_QUERY_FAILED",
    "PG_CONN_TERMINATED",
]
