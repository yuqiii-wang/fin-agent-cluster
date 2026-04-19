"""Database initialisation — creates all application tables and the LangGraph schema."""

from backend.db.postgres.base import Base
from backend.db.postgres.engine import get_engine
from backend.db.postgres.checkpointer import ensure_setup


async def init_db() -> None:
    """Create all SQLAlchemy-managed tables and run LangGraph checkpointer setup.

    ORM models are imported here (not at module level) to avoid circular
    imports between app.db and app.graph.
    """
    # Ensure all ORM models are registered on Base.metadata before create_all.
    import backend.users.models  # noqa: F401
    import backend.graph.models  # noqa: F401

    engine = get_engine()
    async with engine.begin() as conn:
        # Ensure application schemas exist before SQLAlchemy creates tables.
        await conn.exec_driver_sql("CREATE SCHEMA IF NOT EXISTS fin_users")
        await conn.run_sync(Base.metadata.create_all)
    await ensure_setup()
