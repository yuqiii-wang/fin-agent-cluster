"""Database session management for both SQLAlchemy (query logs) and LangGraph checkpointer."""

from contextlib import asynccontextmanager
from typing import AsyncGenerator, Optional

from psycopg import AsyncConnection
from psycopg.rows import dict_row
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver

from app.config import get_settings
from app.models import Base

settings = get_settings()

_sa_url = settings.DATABASE_URL.replace("postgresql://", "postgresql+psycopg://", 1)

_engine: Optional[AsyncEngine] = None
_session_factory: Optional[async_sessionmaker[AsyncSession]] = None


def _get_engine() -> AsyncEngine:
    global _engine, _session_factory
    if _engine is None:
        _engine = create_async_engine(_sa_url, echo=False)
        _session_factory = async_sessionmaker(_engine, class_=AsyncSession, expire_on_commit=False)
    return _engine


def _get_session_factory() -> async_sessionmaker[AsyncSession]:
    _get_engine()
    assert _session_factory is not None
    return _session_factory


_lg_url = settings.DATABASE_URL

_setup_done = False


async def _ensure_setup() -> None:
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


@asynccontextmanager
async def checkpointer() -> AsyncGenerator[AsyncPostgresSaver, None]:
    """Async context manager that provides a checkpointer and ensures the connection is closed."""
    conn = await AsyncConnection.connect(
        _lg_url, autocommit=True, prepare_threshold=0, row_factory=dict_row,
        options="-csearch_path=fin_agents",
    )
    try:
        yield AsyncPostgresSaver(conn)
    finally:
        await conn.close()


async def init_db() -> None:
    """Create application tables and setup LangGraph checkpointer."""
    engine = _get_engine()
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    await _ensure_setup()


@asynccontextmanager
async def get_db() -> AsyncGenerator[AsyncSession, None]:
    factory = _get_session_factory()
    async with factory() as session:
        yield session
