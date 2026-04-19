"""PostgreSQL database management sub-package.

Exposes engine, session factory, raw connection, checkpointer, ORM base.
For task lifecycle event subscriptions use backend.db.postgres.listener.pg_listen
directly to avoid circular imports with backend.sse_notifications.
"""

from backend.db.postgres.base import Base
from backend.db.postgres.engine import get_engine, get_session_factory
from backend.db.postgres.connection import raw_conn
from backend.db.postgres.checkpointer import checkpointer, ensure_setup
from backend.db.postgres.init_ import init_db

__all__ = [
    "Base",
    "get_engine",
    "get_session_factory",
    "raw_conn",
    "checkpointer",
    "ensure_setup",
    "init_db",
]
