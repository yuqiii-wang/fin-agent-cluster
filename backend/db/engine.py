"""SQLAlchemy async engine and session-factory — singleton per process."""

from typing import Optional

from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine

from backend.config import get_settings

_engine: Optional[AsyncEngine] = None
_session_factory: Optional[async_sessionmaker[AsyncSession]] = None


def get_engine() -> AsyncEngine:
    """Return the process-wide SQLAlchemy async engine, creating it on first call."""
    global _engine, _session_factory
    if _engine is None:
        settings = get_settings()
        sa_url = settings.DATABASE_PG_URL.replace("postgresql://", "postgresql+psycopg://", 1)
        _engine = create_async_engine(
            sa_url,
            echo=False,
            connect_args={"connect_timeout": settings.DB_CONNECT_TIMEOUT_SECONDS},
        )
        _session_factory = async_sessionmaker(_engine, class_=AsyncSession, expire_on_commit=False)
    return _engine


def get_session_factory() -> async_sessionmaker[AsyncSession]:
    """Return the process-wide SQLAlchemy session factory."""
    get_engine()
    assert _session_factory is not None
    return _session_factory
