"""LangGraph AsyncPostgresSaver setup and context manager."""

from contextlib import asynccontextmanager
from typing import AsyncGenerator

from psycopg import AsyncConnection
from psycopg.rows import dict_row
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver

from backend.config import get_settings

_setup_done: bool = False


async def ensure_setup() -> None:
    """Run LangGraph checkpointer table setup exactly once per process."""
    global _setup_done
    if not _setup_done:
        settings = get_settings()
        async with await AsyncConnection.connect(
            settings.DATABASE_URL,
            connect_timeout=settings.DB_CONNECT_TIMEOUT_SECONDS,
            autocommit=True,
            prepare_threshold=0,
            row_factory=dict_row,
            options="-csearch_path=fin_agents",
        ) as conn:
            cp = AsyncPostgresSaver(conn)
            await cp.setup()
        _setup_done = True


@asynccontextmanager
async def checkpointer() -> AsyncGenerator[AsyncPostgresSaver, None]:
    """Async context manager that yields a ready-to-use AsyncPostgresSaver."""
    settings = get_settings()
    conn = await AsyncConnection.connect(
        settings.DATABASE_URL,
        connect_timeout=settings.DB_CONNECT_TIMEOUT_SECONDS,
        autocommit=True,
        prepare_threshold=0,
        row_factory=dict_row,
        options="-csearch_path=fin_agents",
    )
    try:
        yield AsyncPostgresSaver(conn)
    finally:
        await conn.close()
