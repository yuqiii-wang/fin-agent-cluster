"""FastAPI application for financial agent cluster."""

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI

from backend.db import init_db, raw_conn
from backend.api.router import router as api_router
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
        async with raw_conn() as conn:
            cur = await conn.execute("SELECT 1")
            await cur.fetchone()
        logger.info("[startup] database connection OK")
    except Exception as exc:
        raise RuntimeError(f"[startup] database connection failed: {exc}") from exc


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
    await _check_db_conn()
    await init_db()
    yield


app = FastAPI(title="Financial Agent Cluster", version="1.0.0", lifespan=lifespan)

app.include_router(api_router)


@app.get("/health")
async def health() -> dict:
    """Health check endpoint."""
    return {
        "status": "ok",
        "llm_provider": get_active_provider(),
        "embedding_provider": get_active_embedding_provider(),
    }

