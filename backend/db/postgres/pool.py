"""Shared AsyncConnectionPool instances for the FastAPI process.

Three pools are managed here:

* **checkpointer_pool** — used exclusively by the LangGraph
  :class:`~langgraph.checkpoint.postgres.aio.AsyncPostgresSaver`.
  Always targets the **primary** (write) node; LangGraph needs consistent
  reads immediately after writes.  ``autocommit=True``, ``prepare_threshold=0``.

* **raw_pool** — used by :func:`~backend.db.postgres.connection.raw_conn`
  for write operations (INSERT / UPDATE / DELETE / NOTIFY) and any query
  that requires read-after-write consistency.  Targets the **primary**.

* **raw_read_pool** — used by ``raw_conn(readonly=True)`` for pure SELECT
  queries.  Targets the **replica** when ``DATABASE_PG_READ_URL`` is set,
  otherwise falls back to the primary so single-instance deployments keep
  working without configuration.

All pools are opened during the FastAPI lifespan and closed on shutdown.
Call :func:`open_pools` once at startup and :func:`close_pools` on shutdown.
"""

from __future__ import annotations

import logging

from psycopg.rows import dict_row
from psycopg_pool import AsyncConnectionPool

from backend.config import get_settings
from backend.db.postgres.errors import PG_POOL_NOT_OPENED

logger = logging.getLogger(__name__)

_checkpointer_pool: AsyncConnectionPool | None = None
_raw_pool: AsyncConnectionPool | None = None
_raw_read_pool: AsyncConnectionPool | None = None

DEFAULT_SEARCH_PATH = "fin_markets,fin_agents,public"
_DEFAULT_SEARCH_PATH = DEFAULT_SEARCH_PATH  # internal alias


async def open_pools() -> None:
    """Open all three connection pools.  Called once in the FastAPI lifespan."""
    global _checkpointer_pool, _raw_pool, _raw_read_pool
    settings = get_settings()
    write_url = settings.DATABASE_PG_URL
    read_url = settings.DATABASE_PG_READ_URL or write_url

    if _checkpointer_pool is None:
        _checkpointer_pool = AsyncConnectionPool(
            conninfo=write_url,
            min_size=2,
            max_size=10,
            open=False,
            kwargs={
                "autocommit": True,
                "prepare_threshold": 0,
                "row_factory": dict_row,
                "options": "-csearch_path=fin_agents",
            },
        )
        await _checkpointer_pool.open()
        logger.info("[pool] checkpointer pool opened (primary min=2 max=10)")

    if _raw_pool is None:
        _raw_pool = AsyncConnectionPool(
            conninfo=write_url,
            min_size=10,
            max_size=100,
            open=False,
            kwargs={
                "autocommit": True,
                "row_factory": dict_row,
                "options": f"-csearch_path={_DEFAULT_SEARCH_PATH}",
            },
        )
        await _raw_pool.open()
        logger.info("[pool] raw write pool opened (primary min=2 max=10)")

    if _raw_read_pool is None:
        _raw_read_pool = AsyncConnectionPool(
            conninfo=read_url,
            min_size=2,
            max_size=10,
            open=False,
            kwargs={
                "autocommit": True,
                "row_factory": dict_row,
                "options": f"-csearch_path={_DEFAULT_SEARCH_PATH}",
            },
        )
        await _raw_read_pool.open()
        target = "replica" if read_url != write_url else "primary (no replica configured)"
        logger.info("[pool] raw read pool opened (%s min=2 max=10)", target)


async def close_pools() -> None:
    """Close all three connection pools.  Called on FastAPI shutdown."""
    global _checkpointer_pool, _raw_pool, _raw_read_pool
    if _checkpointer_pool is not None:
        await _checkpointer_pool.close()
        _checkpointer_pool = None
        logger.info("[pool] checkpointer pool closed")
    if _raw_pool is not None:
        await _raw_pool.close()
        _raw_pool = None
        logger.info("[pool] raw write pool closed")
    if _raw_read_pool is not None:
        await _raw_read_pool.close()
        _raw_read_pool = None
        logger.info("[pool] raw read pool closed")


def get_checkpointer_pool() -> AsyncConnectionPool:
    """Return the shared checkpointer pool (primary).  Must call :func:`open_pools` first."""
    if _checkpointer_pool is None:
        raise RuntimeError(f"[{PG_POOL_NOT_OPENED}] Connection pools not opened — call open_pools() in lifespan")
    return _checkpointer_pool


def get_raw_pool() -> AsyncConnectionPool:
    """Return the shared raw-write pool (primary).  Must call :func:`open_pools` first."""
    if _raw_pool is None:
        raise RuntimeError(f"[{PG_POOL_NOT_OPENED}] Connection pools not opened — call open_pools() in lifespan")
    return _raw_pool


def get_raw_read_pool() -> AsyncConnectionPool:
    """Return the shared raw-read pool (replica or primary).  Must call :func:`open_pools` first."""
    if _raw_read_pool is None:
        raise RuntimeError(f"[{PG_POOL_NOT_OPENED}] Connection pools not opened — call open_pools() in lifespan")
    return _raw_read_pool
