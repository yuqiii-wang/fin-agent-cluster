"""app.db -- centralised database management package.

Sub-packages:
    backend.db.postgres  -- PostgreSQL engine, sessions, checkpointer, raw connections
    backend.db.redis     -- Redis Streams token publisher (via Centrifugo)

Public surface::

    from backend.db import init_db, checkpointer, get_session_factory, raw_conn
    from backend.db import stream_token
"""

from backend.db.postgres.init_ import init_db
from backend.db.postgres.checkpointer import checkpointer, get_pool_checkpointer
from backend.db.postgres.engine import get_session_factory, get_read_session_factory
from backend.db.postgres.connection import raw_conn
from backend.db.redis.streams.publisher import stream_token

__all__ = [
    "init_db",
    "checkpointer",
    "get_pool_checkpointer",
    "get_session_factory",
    "get_read_session_factory",
    "raw_conn",
    "stream_token",
]
