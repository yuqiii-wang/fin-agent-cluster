"""FastAPI application for financial agent cluster."""

import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI

from backend.db import init_db, raw_conn
from backend.api.router import router as api_router
from backend.graph.errors import GRAPH_DB_UNAVAILABLE
from backend.llm.factory import get_active_provider, set_provider_override
from backend.llm.embeddings import (
    get_active_embedding_provider,
    set_embedding_provider_override,
)
from backend.llm.providers.embedding_ollama import probe_ollama_embedding

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
        raise RuntimeError(f"[{GRAPH_DB_UNAVAILABLE}] database connection failed: {exc}") from exc


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Manage app startup and shutdown."""
    # Probe Ollama first; if reachable, use it as the LLM provider (no proxy needed
    # for local connections — proxy bypass is handled inside the Ollama provider).
    from backend.llm.providers.ollama import probe_ollama
    if probe_ollama():
        logger.info("[startup] Ollama reachable — switching LLM provider to ollama (proxy bypassed)")
        set_provider_override("ollama")

        # Separate health check for embeddings: use a greeting probe text and only
        # override embedding provider when a valid vector is returned.
        if probe_ollama_embedding():
            logger.info("[startup] Ollama embedding reachable — switching EMBEDDING_PROVIDER to ollama")
            set_embedding_provider_override("ollama")
        else:
            logger.info("[startup] Ollama embedding not reachable — using configured EMBEDDING_PROVIDER")
    else:
        logger.info("[startup] Ollama not reachable — using configured LLM_PROVIDER")
    # Open shared PostgreSQL connection pools first — raw_conn() and the
    # checkpointer both draw from these pools; must be open before any DB call.
    from backend.db.postgres.pool import open_pools, close_pools as _close_pools
    await open_pools()
    await _check_db_conn()
    await init_db()
    # Pre-compile the unified LangGraph graph with a pooled AsyncPostgresSaver.
    # Eliminates per-query graph rebuild (~5–20 ms) and cold PG connect (~10–50 ms).
    from backend.graph.compiled import init_compiled_graph
    await init_compiled_graph()
    # Warm static catalog strings used by the query_optimizer prompt.
    # Eliminates 3 raw DB connections on every first query after startup.
    from backend.db.postgres.queries.fin_markets_region import warm_prompt_catalogs
    await warm_prompt_catalogs()
    # Pre-warm the LLM client so @lru_cache is populated before the first query.
    # Eliminates cold provider initialisation (~50–200 ms) on the first request.
    from backend.llm.factory import get_llm
    try:
        get_llm()
        logger.info("[startup] LLM client pre-warmed provider=%s", get_active_provider())
    except Exception as exc:
        logger.warning("[startup] LLM pre-warm failed (non-fatal): %s", exc)
    # Clear stale task_active:* Redis keys left by the previous server process.
    # Without this, orphan detection (is_task_active_any_instance) would return
    # True for old threads and SSE clients would hang indefinitely on hot switch.
    from backend.api.registry import clear_all_task_active_flags
    await clear_all_task_active_flags()
    # Purge leftover fin:perf:* and watch:* Redis keys from previous runs.
    # Perf-test streams carry no TTL; without this they accumulate (≈1–2 MB
    # per stream key) and survive across restarts.
    from backend.db.redis.lock_manager.session_cleanup import purge_stale_perf_streams
    await purge_stale_perf_streams()
    # Ensure all Redis Stream consumer groups exist before workers start.
    from backend.streaming.streams import ensure_all_groups
    await ensure_all_groups()
    # Start cancel signal listener: cancels local asyncio.Tasks when cancel is called on any instance.
    from backend.db.redis.session.cancel_signal import run_cancel_listener
    from backend.api.registry import running_tasks
    _cancel_task = asyncio.create_task(run_cancel_listener(running_tasks))
    # Start stream consumers: prefer Celery workers; fall back to FastAPI threads.
    from backend.streaming.fallback import celery_workers_available, start_fallback_workers
    _fallback_tasks: list = []
    if await celery_workers_available():
        logger.info("[startup] Celery workers detected — LLM invocations delegated to Celery")
    else:
        _fallback_tasks = await start_fallback_workers()
    yield
    # Cancel the cancel-signal listener on shutdown.
    _cancel_task.cancel()
    # Cancel fallback tasks on shutdown (no-op if Celery was used)
    for task in _fallback_tasks:
        task.cancel()
    # Close shared PostgreSQL connection pools.
    await _close_pools()


app = FastAPI(title="Financial Agent Cluster", version="1.0.0", lifespan=lifespan)

app.include_router(api_router)


@app.get("/health")
@app.get("/api/v1/health")
async def health() -> dict:
    """Health check endpoint (also reachable via /api/v1/health for Kong routing)."""
    return {
        "status": "ok",
        "llm_provider": get_active_provider(),
        "embedding_provider": get_active_embedding_provider(),
    }

