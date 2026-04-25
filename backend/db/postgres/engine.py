"""SQLAlchemy async engine and session-factory — singleton per process.

Two engines are maintained:

* **write engine** (``get_engine()``) — targets the primary.  Used for
  ORM writes, ``init_db()``, and reads that need read-after-write consistency.

* **read engine** (``get_read_engine()``) — targets the replica when
  ``DATABASE_PG_READ_URL`` is set; falls back to the primary so single-instance
  deployments work without configuration.
"""

from typing import Optional

from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine

from backend.config import get_settings

_engine: Optional[AsyncEngine] = None
_session_factory: Optional[async_sessionmaker[AsyncSession]] = None
_read_engine: Optional[AsyncEngine] = None
_read_session_factory: Optional[async_sessionmaker[AsyncSession]] = None


def _build_engine(url: str) -> AsyncEngine:
    """Create a SQLAlchemy async engine for *url*.

    Args:
        url: PostgreSQL asyncpg-compatible URL.

    Returns:
        Configured :class:`~sqlalchemy.ext.asyncio.AsyncEngine`.
    """
    sa_url = url.replace("postgresql://", "postgresql+psycopg://", 1)
    settings = get_settings()
    return create_async_engine(
        sa_url,
        echo=False,
        connect_args={"connect_timeout": settings.DB_CONNECT_TIMEOUT_SECONDS},
    )


def get_engine() -> AsyncEngine:
    """Return the process-wide SQLAlchemy write engine (primary), creating it on first call."""
    global _engine, _session_factory
    if _engine is None:
        settings = get_settings()
        _engine = _build_engine(settings.DATABASE_PG_URL)
        _session_factory = async_sessionmaker(_engine, class_=AsyncSession, expire_on_commit=False)
    return _engine


def get_session_factory() -> async_sessionmaker[AsyncSession]:
    """Return the process-wide SQLAlchemy write session factory (primary)."""
    get_engine()
    assert _session_factory is not None
    return _session_factory


def get_read_engine() -> AsyncEngine:
    """Return the process-wide SQLAlchemy read engine (replica or primary), creating it on first call."""
    global _read_engine, _read_session_factory
    if _read_engine is None:
        settings = get_settings()
        read_url = settings.DATABASE_PG_READ_URL or settings.DATABASE_PG_URL
        _read_engine = _build_engine(read_url)
        _read_session_factory = async_sessionmaker(
            _read_engine, class_=AsyncSession, expire_on_commit=False
        )
    return _read_engine


def get_read_session_factory() -> async_sessionmaker[AsyncSession]:
    """Return the process-wide SQLAlchemy read session factory (replica or primary)."""
    get_read_engine()
    assert _read_session_factory is not None
    return _read_session_factory
