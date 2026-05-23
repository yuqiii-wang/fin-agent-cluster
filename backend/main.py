"""FastAPI application for financial agent cluster — main thread."""

import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.responses import Response
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest

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

    # Pre-load macro instrument lists (economics + market_index) into the in-process
    # cache so analyze_economics and prepare_index nodes never hit the DB on first run.
    from backend.db.postgres.queries.fin_markets_macro import warm_macro_instruments
    await warm_macro_instruments()

    # Pre-load market index definitions into the in-process cache so stats calculations
    # can resolve exchange → index → currency without per-request DB round-trips.
    from backend.db.postgres.queries.fin_markets_indexes import warm_market_indexes
    await warm_market_indexes()

    # Kill zombie Celery tasks from any previous process before re-dispatching
    # recoveries — prevents stale workers running in parallel with fresh tasks.
    from backend.main_thread import cleanup_stale_celery_tasks
    await cleanup_stale_celery_tasks()

    # Recover any graph runs that were active on this port during a previous
    # (crashed/restarted) process.  Must run after pools and graph are ready.
    from backend.main_thread import recover_running_threads
    await recover_running_threads()

    yield

    # ── Shutdown ────────────────────────────────────────────────────────────
    # Cancel all active threads first so _await_result polling loops exit
    # quickly (via Redis cancel flag), then drain the remaining asyncio tasks
    # before closing DB pools.
    from backend.langgraph.lifecycle.threads import pause_all_running_tasks_on_shutdown
    await pause_all_running_tasks_on_shutdown()
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


@app.get("/metrics")
async def metrics() -> Response:
    """Expose Prometheus metrics for this FastAPI instance."""
    return Response(content=generate_latest(), media_type=CONTENT_TYPE_LATEST)

