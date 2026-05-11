"""PostgreSQL database management sub-package.

Exposes engine, session factory, raw connection, checkpointer, ORM base.
PostgreSQL is used exclusively for persistence.  Lifecycle event delivery
uses Redis Pub/Sub (see backend.db.redis.lifecycle.subscriber).

Read / write routing
--------------------
* ``raw_conn()`` → primary (write pool)
* ``raw_conn(readonly=True)`` → replica read pool (falls back to primary when
  no replica is configured).
* ``get_session_factory()`` → primary session factory
* ``get_read_session_factory()`` → replica session factory (or primary fallback)
"""

from backend.db.postgres.base import Base
from backend.db.postgres.engine import (
    get_engine,
    get_read_engine,
    get_read_session_factory,
    get_session_factory,
)
from backend.db.postgres.connection import raw_conn
from backend.db.postgres.checkpointer import checkpointer, ensure_setup, get_pool_checkpointer
from backend.db.postgres.init_ import init_db
from backend.db.postgres.pool import (
    open_pools,
    close_pools,
    get_checkpointer_pool,
    get_raw_pool,
    get_raw_read_pool,
)
from backend.db.postgres.types import QueryStatus, query_status_sa_type, WorkStatus, work_status_sa_type, NodeType, node_type_sa_type

__all__ = [
    "Base",
    "get_engine",
    "get_read_engine",
    "get_session_factory",
    "get_read_session_factory",
    "raw_conn",
    "checkpointer",
    "ensure_setup",
    "get_pool_checkpointer",
    "init_db",
    "open_pools",
    "close_pools",
    "get_checkpointer_pool",
    "get_raw_pool",
    "get_raw_read_pool",
    "QueryStatus",
    "query_status_sa_type",
    "WorkStatus",
    "work_status_sa_type",
    "NodeType",
    "node_type_sa_type",
]
