"""FastAPI application for assistant instances.

Assistant instances handle non-LangGraph requests: query status reads,
cancellation, auth, Centrifugo token, reports, tasks metadata, quant data,
and thread inspection.

Excluded from assistants (runner-only):
- LangGraph graph compilation and execution
- Celery fallback worker startup
- Cancel-signal Redis listener (runners manage running tasks)
- Stale task_active flag cleanup (owned by runners on startup)
- Redis Stream consumer-group creation (owned by runners)
"""

from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI

from backend.db import init_db, raw_conn
from backend.assistant.router import router as assistant_router
from backend.graph.errors import GRAPH_DB_UNAVAILABLE
from backend.llm.embeddings import get_active_embedding_provider

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
        logger.info("[startup:assistant] database connection OK")
    except Exception as exc:
        raise RuntimeError(
            f"[{GRAPH_DB_UNAVAILABLE}] database connection failed: {exc}"
        ) from exc


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Manage assistant app startup and shutdown.

    Connects to DB and Redis; does NOT start LangGraph, Celery, or the
    cancel-signal listener.  Starts the status-verifier background task that
    re-delivers unACKed query-status phases to connected clients.
    """
    from backend.db.postgres.pool import open_pools, close_pools as _close_pools

    await open_pools()
    await _check_db_conn()
    await init_db()

    # Warm static catalog strings — pure DB reads, safe on assistant instances.
    from backend.db.postgres.queries.fin_markets_region import warm_prompt_catalogs

    await warm_prompt_catalogs()

    # Start the query-status ACK verifier: re-publishes unACKed lifecycle phases
    # so clients that miss events during WS reconnects still get them.
    from backend.assistant.status_verifier import run_status_verifier

    verifier_task = asyncio.create_task(run_status_verifier(), name="status_verifier")

    logger.info("[startup:assistant] ready — LangGraph and Celery are disabled on this instance")
    yield

    verifier_task.cancel()
    try:
        await verifier_task
    except asyncio.CancelledError:
        pass

    await _close_pools()


app = FastAPI(
    title="Financial Agent Cluster — Assistant",
    version="1.0.0",
    lifespan=lifespan,
)

app.include_router(assistant_router)


@app.get("/health")
async def health() -> dict:
    """Health check endpoint."""
    return {
        "status": "ok",
        "instance_type": "assistant",
        "embedding_provider": get_active_embedding_provider(),
    }
