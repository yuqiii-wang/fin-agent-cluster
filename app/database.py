"""Database session management for both SQLAlchemy (query logs) and LangGraph checkpointer."""

import asyncio
import selectors
from contextlib import asynccontextmanager

from psycopg import AsyncConnection
from psycopg.rows import dict_row
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver

from app.config import get_settings
from app.models import Base

settings = get_settings()

_sa_url = settings.DATABASE_URL.replace("postgresql://", "postgresql+psycopg://", 1)

_engine = None
_session_factory = None


def _get_engine():
    global _engine, _session_factory
    if _engine is None:
        _engine = create_async_engine(_sa_url, echo=False)
        _session_factory = async_sessionmaker(_engine, class_=AsyncSession, expire_on_commit=False)
    return _engine


def _get_session_factory():
    _get_engine()
    return _session_factory


_lg_url = settings.DATABASE_URL

_setup_done = False


async def _ensure_setup():
    """Run checkpointer setup once to create LangGraph tables."""
    global _setup_done
    if not _setup_done:
        async with await AsyncConnection.connect(
            _lg_url, autocommit=True, prepare_threshold=0, row_factory=dict_row,
            options="-csearch_path=fin_agents",
        ) as conn:
            cp = AsyncPostgresSaver(conn)
            await cp.setup()
        _setup_done = True


async def get_checkpointer() -> AsyncPostgresSaver:
    """Get a fresh AsyncPostgresSaver instance for graph execution."""
    conn = await AsyncConnection.connect(
        _lg_url, autocommit=True, prepare_threshold=0, row_factory=dict_row,
        options="-csearch_path=fin_agents",
    )
    return AsyncPostgresSaver(conn)


async def close_checkpointer(cp: AsyncPostgresSaver):
    """Close the checkpointer connection."""
    await cp.conn.close()


async def init_db():
    """Create application tables and setup LangGraph checkpointer."""
    engine = _get_engine()
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    await _ensure_setup()


async def get_db() -> AsyncSession:
    factory = _get_session_factory()
    async with factory() as session:
        yield session
