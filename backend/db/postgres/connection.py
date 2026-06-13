"""Raw psycopg3 async connection context manager for direct SQL execution.

Write operations (INSERT / UPDATE / DELETE / NOTIFY) and read-after-write queries
use the **primary** pool (``get_raw_pool()``).

Pure SELECT queries should pass ``readonly=True`` to be routed to the **replica**
pool (``get_raw_read_pool()``).  When no replica is configured both pools target
the primary, so the parameter is safe to add without any infrastructure change.

For the default search_path (``fin_markets,fin_agents,public``) connections are
acquired from the appropriate shared pool -- zero TCP overhead per call after
pool open.

For non-default search_paths a dedicated connection is opened and closed for
that call (rare in practice; all hot-path callers use the default).

:func:`pg_retry` -- decorator that retries a DB coroutine once on transient
``psycopg.OperationalError`` (covers ``AdminShutdown``, broken-pipe, etc.).
The pool discards the broken connection automatically; the retry acquires a
fresh one.
"""

import functools
import logging
from contextlib import asynccontextmanager
from typing import AsyncGenerator, Callable, TypeVar

import psycopg
from psycopg import AsyncConnection
from psycopg.rows import dict_row

from backend.config import get_settings
from backend.db.postgres.pool import DEFAULT_SEARCH_PATH as _DEFAULT_SEARCH_PATH

_logger = logging.getLogger(__name__)
_T = TypeVar("_T")


def pg_retry(max_retries: int = 1) -> Callable:
    """Decorator: retry the wrapped async DB coroutine on transient connection errors.

    ``psycopg.OperationalError`` covers server-side terminations such as
    ``AdminShutdown``, broken-pipe after idle-timeout, and similar transient
    faults.  The pool automatically discards the broken connection on exit, so
    the retry always acquires a fresh one.

    Non-transient errors (``IntegrityError``, ``ProgrammingError``, etc.) are
    not caught and propagate immediately.

    Args:
        max_retries: Number of additional attempts after the first failure.
            Defaults to 1 (two attempts total).
    """
    def decorator(fn: Callable[..., _T]) -> Callable[..., _T]:
        @functools.wraps(fn)
        async def wrapper(*args, **kwargs):  # type: ignore[return]
            for attempt in range(max_retries + 1):
                try:
                    return await fn(*args, **kwargs)
                except psycopg.OperationalError as exc:
                    if attempt >= max_retries:
                        raise
                    _logger.error(
                        "[PG_CONN_TERMINATED] transient DB error in %s (attempt %d/%d), retrying: %s",
                        fn.__qualname__, attempt + 1, max_retries + 1, exc,
                    )
        return wrapper  # type: ignore[return-value]
    return decorator


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
            Defaults to ``'fin_markets,fin_agents,public'``.
        readonly:    When ``True``, acquire from the read-replica pool.
            Defaults to ``False`` (primary/write pool).
    """
    if search_path == _DEFAULT_SEARCH_PATH:
        # Hot path: acquire from the appropriate pool -- no TCP overhead.
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
            pass  # pool not opened -- fall through to direct connection

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
