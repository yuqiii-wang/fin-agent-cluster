"""PostgreSQL database management sub-package.

Exposes engine, session factory, raw connection, checkpointer, ORM base.
Lifecycle event subscriptions are handled by backend.db.redis.lifecycle_subscriber;
the fanout task (backend.db.redis.lifecycle_fanout) holds the single shared
PG LISTEN connection.
"""

from backend.db.postgres.base import Base
from backend.db.postgres.engine import get_engine, get_session_factory
from backend.db.postgres.connection import raw_conn
from backend.db.postgres.checkpointer import checkpointer, ensure_setup
from backend.db.postgres.init_ import init_db
from backend.db.postgres.types import QueryStatus, query_status_sa_type, StreamingStatus, streaming_status_sa_type

__all__ = [
    "Base",
    "get_engine",
    "get_session_factory",
    "raw_conn",
    "checkpointer",
    "ensure_setup",
    "init_db",
    "QueryStatus",
    "query_status_sa_type",
    "StreamingStatus",
    "streaming_status_sa_type",
]
