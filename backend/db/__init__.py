"""app.db — centralised database management package.

Sub-packages:
    backend.db.postgres  — PostgreSQL engine, sessions, checkpointer, raw connections
    backend.db.redis     — Redis Streams token publisher / subscriber

Public surface::

    from backend.db import init_db, checkpointer, get_session_factory, raw_conn
    from backend.db import stream_token, delete_stream, read_stream

For SSE lifecycle notifications use backend.sse_notifications.
For pg_listen use backend.db.postgres.listener directly.
"""

from backend.db.postgres.init_ import init_db
from backend.db.postgres.checkpointer import checkpointer
from backend.db.postgres.engine import get_session_factory
from backend.db.postgres.connection import raw_conn
from backend.db.redis.publisher import stream_token, delete_stream
from backend.db.redis.subscriber import read_stream

__all__ = [
    "init_db",
    "checkpointer",
    "get_session_factory",
    "raw_conn",
    "stream_token",
    "delete_stream",
    "read_stream",
]
