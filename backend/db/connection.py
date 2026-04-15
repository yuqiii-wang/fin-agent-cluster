"""Raw psycopg3 async connection context manager for direct SQL execution."""

from contextlib import asynccontextmanager
from typing import AsyncGenerator

from psycopg import AsyncConnection
from psycopg.rows import dict_row

from backend.config import get_settings


@asynccontextmanager
async def raw_conn(
    search_path: str = "fin_markets,fin_agents",
) -> AsyncGenerator[AsyncConnection, None]:
    """Yield a bare autocommit psycopg3 connection scoped to *search_path*.

    Args:
        search_path: PostgreSQL search_path string applied to the connection.
            Defaults to ``'fin_markets,fin_agents'``.
    """
    settings = get_settings()
    conn = await AsyncConnection.connect(
        settings.DATABASE_URL,
        connect_timeout=settings.DB_CONNECT_TIMEOUT_SECONDS,
        autocommit=True,
        row_factory=dict_row,
        options=f"-csearch_path={search_path}",
    )
    try:
        yield conn
    finally:
        await conn.close()
