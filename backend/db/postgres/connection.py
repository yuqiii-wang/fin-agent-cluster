"""Raw psycopg3 async connection context manager for direct SQL execution.

Write operations (INSERT / UPDATE / DELETE / NOTIFY) and read-after-write queries
use the **primary** pool (``get_raw_pool()``).

Pure SELECT queries should pass ``readonly=True`` to be routed to the **replica**
pool (``get_raw_read_pool()``).  When no replica is configured both pools target
the primary, so the parameter is safe to add without any infrastructure change.

For the default search_path (``fin_markets,fin_agents``) connections are
acquired from the appropriate shared pool — zero TCP overhead per call after
pool open.

For non-default search_paths a dedicated connection is opened and closed for
that call (rare in practice; all hot-path callers use the default).
"""

from contextlib import asynccontextmanager
from typing import AsyncGenerator

from psycopg import AsyncConnection
from psycopg.rows import dict_row

from backend.config import get_settings

_DEFAULT_SEARCH_PATH = "fin_markets,fin_agents"


@asynccontextmanager
async def raw_conn(
    search_path: str = _DEFAULT_SEARCH_PATH,
    readonly: bool = False,
) -> AsyncGenerator[AsyncConnection, None]:
    """Yield a bare autocommit psycopg3 connection scoped to *search_path*.

    Routes to the replica pool when ``readonly=True`` (pure SELECTs); routes
    to the primary pool otherwise (writes, NOTIFY, read-after-write SELECTs).
    Falls back to the primary pool when no replica is configured.

    Uses the shared connection pool for the default search_path, eliminating
    the TCP handshake and auth round-trip on every call.  A fresh connection
    is opened only when a non-default *search_path* is requested.

    Args:
        search_path: PostgreSQL search_path string applied to the connection.
            Defaults to ``'fin_markets,fin_agents'``.
        readonly:    When ``True``, acquire from the read-replica pool.
            Defaults to ``False`` (primary/write pool).
    """
    if search_path == _DEFAULT_SEARCH_PATH:
        # Hot path: acquire from the appropriate pool — no TCP overhead.
        # Falls back to a direct connection when the pool is not open
        # (e.g. Celery worker processes that never call open_pools()).
        pool = None
        try:
            if readonly:
                from backend.db.postgres.pool import get_raw_read_pool
                pool = get_raw_read_pool()
            else:
                from backend.db.postgres.pool import get_raw_pool
                pool = get_raw_pool()
        except RuntimeError:
            pass  # pool not opened — fall through to direct connection

        if pool is not None:
            async with pool.connection() as conn:
                yield conn
            return
        # Cold path: dedicated connection for custom search_path (rare).
        settings = get_settings()
        url = (
            settings.DATABASE_PG_READ_URL
            if (readonly and settings.DATABASE_PG_READ_URL)
            else settings.DATABASE_PG_URL
        )
        conn = await AsyncConnection.connect(
            url,
            connect_timeout=settings.DB_CONNECT_TIMEOUT_SECONDS,
            autocommit=True,
            row_factory=dict_row,
            options=f"-csearch_path={search_path}",
        )
        try:
            yield conn
        finally:
            await conn.close()
