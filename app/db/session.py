"""SQLAlchemy async session factory for the repository layer.

A separate engine from ``app.database`` so the repo layer can be configured
independently (autocommit, echo, pool size) without affecting the LangGraph
checkpointer connection.
"""

from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine

from app.config import get_settings

_engine: AsyncEngine | None = None
_factory: async_sessionmaker[AsyncSession] | None = None


def get_session_factory() -> async_sessionmaker[AsyncSession]:
    """Return a shared async session factory (lazy initialised).

    Returns:
        ``async_sessionmaker`` bound to the project's PostgreSQL database.
    """
    global _engine, _factory
    if _factory is None:
        settings = get_settings()
        sa_url = settings.DATABASE_URL.replace("postgresql://", "postgresql+psycopg://", 1)
        _engine = create_async_engine(sa_url, echo=False, pool_pre_ping=True)
        _factory = async_sessionmaker(
            _engine,
            class_=AsyncSession,
            autoflush=False,
            autocommit=False,
            expire_on_commit=False,
        )
    return _factory
