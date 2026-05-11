"""FastAPI application for financial agent cluster — main thread."""

import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI

from backend.db import init_db, raw_conn
from backend.api.router import router as api_router
logger = logging.getLogger(__name__)


async def _check_db_conn() -> None:
    """Verify the database is reachable during startup.

    Raises:
        RuntimeError: If the database connection cannot be established.
    """
    try:
        async with raw_conn(readonly=True) as conn:
            cur = await conn.execute("SELECT 1")
            await cur.fetchone()
        logger.info("[startup] database connection OK")
    except Exception as exc:
        raise RuntimeError(f"[startup] database connection failed: {exc}") from exc


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Manage app startup and shutdown for this main thread instance."""
    logger.info("[startup] using mock LLM provider")
    logger.info("[startup] using mock embedding provider")
    # Open shared PostgreSQL connection pools first — raw_conn() and the
    # checkpointer both draw from these pools; must be open before any DB call.
    from backend.db.postgres.pool import open_pools, close_pools as _close_pools
    await open_pools()
    await _check_db_conn()
    await init_db()
    # Pre-compile the unified LangGraph graph with a pooled AsyncPostgresSaver.
    # Eliminates per-query graph rebuild (~5–20 ms) and cold PG connect (~10–50 ms).
    from backend.langgraph.compiled import init_compiled_graph
    await init_compiled_graph()

    # Recover any graph runs that were active on this port during a previous
    # (crashed/restarted) process.  Must run after pools and graph are ready.
    from backend.main_thread import recover_running_threads
    await recover_running_threads()

    yield

    # ── Shutdown ────────────────────────────────────────────────────────────
    # Drain all in-flight graph tasks before closing DB pools so running
    # graphs can persist their final state and emit completion SSE events.
    from backend.main_thread import wait_all
    await wait_all()
    await _close_pools()

app = FastAPI(title="Financial Agent Cluster", version="1.0.0", lifespan=lifespan)

app.include_router(api_router)


@app.get("/health")
async def health() -> dict:
    """Health check endpoint."""
    return {
        "status": "ok",
    }

