"""LangGraph AsyncPostgresSaver setup and context manager."""

import asyncio
import logging
from contextlib import asynccontextmanager
from typing import AsyncGenerator

import redis.asyncio as aioredis
from psycopg import AsyncConnection
from psycopg.errors import UniqueViolation
from psycopg.rows import dict_row
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver

from backend.config import get_settings
from backend.db.redis.lock_manager import RedisLock
from backend.db.redis.router import get_redis_router

logger = logging.getLogger(__name__)

_setup_done: bool = False

# All global/shared keys live on shard 0 (not thread-routed).
_SETUP_LOCK_KEY = "lock:checkpointer_setup"
_SETUP_DONE_KEY = "flag:checkpointer_setup_done"
_SETUP_LOCK_TTL = 60          # seconds; well above the time setup takes
_SETUP_LOCK_RETRY_INTERVAL = 1.0  # seconds between acquire attempts
_SETUP_LOCK_MAX_RETRIES = 30      # 30 x 1 s = 30 s maximum wait


async def ensure_setup() -> None:
    """Run LangGraph checkpointer table setup exactly once cluster-wide.

    ``_setup_done`` is process-local — each Uvicorn/Celery worker process
    has its own copy.  The cross-process truth is held in Redis shard 0 as
    ``flag:checkpointer_setup_done``.  The lock on ``lock:checkpointer_setup``
    prevents two workers from calling ``cp.setup()`` simultaneously.

    Flow
    ----
    1. Fast-path: process-local ``_setup_done`` (already ran in this process).
    2. Pre-lock Redis check: if the sentinel exists another process already
       finished setup — warm the local flag and return.
    3. Acquire lock (retry up to 30 s).
    4. Inner Redis re-check inside the lock (double-checked locking).
    5. Run ``cp.setup()``.  ``UniqueViolation`` is logged as a warning and
       treated as success (tables already present is a valid terminal state).
    6. Write the Redis sentinel to mark setup done cluster-wide.
    7. Release lock unconditionally (``finally``).
    8. Post-lock safety check: verify the sentinel exists.  Raise
       ``RuntimeError`` if not — setup must have failed.
    """
    global _setup_done

    # --- 1. fast path: process already ran setup ---
    if _setup_done:
        return

    router = get_redis_router()
    # Global keys always target shard 0 — not thread-routed.
    lock_client = aioredis.from_url(router.get_url_at(0), decode_responses=True)
    try:
        # --- 2. pre-lock Redis check ---
        if await lock_client.exists(_SETUP_DONE_KEY):
            _setup_done = True
            logger.debug("[checkpointer] setup already done (Redis sentinel)")
            return

        lock = RedisLock(
            lock_client,
            _SETUP_LOCK_KEY,
            ttl=_SETUP_LOCK_TTL,
            renewal_interval=10,
            parent_poll_interval=0,  # short-lived op; no parent-task guard
        )

        # --- 3. acquire lock with retry ---
        for _ in range(_SETUP_LOCK_MAX_RETRIES):
            if await lock.acquire():
                break
            await asyncio.sleep(_SETUP_LOCK_RETRY_INTERVAL)
        else:
            raise RuntimeError(
                f"[checkpointer] timed out waiting for {_SETUP_LOCK_KEY} "
                f"after {_SETUP_LOCK_MAX_RETRIES}s"
            )

        try:
            # --- 4. inner re-check inside the lock ---
            if await lock_client.exists(_SETUP_DONE_KEY):
                _setup_done = True
                logger.debug(
                    "[checkpointer] setup done by another process (sentinel set while waiting)"
                )
                return  # lock released by finally below

            # --- 5. run migrations ---
            settings = get_settings()
            async with await AsyncConnection.connect(
                settings.DATABASE_PG_URL,
                connect_timeout=settings.DB_CONNECT_TIMEOUT_SECONDS,
                autocommit=True,
                prepare_threshold=0,
                row_factory=dict_row,
                options="-csearch_path=fin_agents",
            ) as conn:
                cp = AsyncPostgresSaver(conn)
                try:
                    await cp.setup()
                    logger.info("[checkpointer] migrations applied successfully")
                except UniqueViolation as exc:
                    # Tables already exist — another process ran setup outside
                    # the lock window (e.g. Redis was briefly unavailable).
                    # Log visibly; tables being present is a valid success state.
                    logger.warning(
                        "[checkpointer] UniqueViolation during setup — "
                        "migrations already applied by another process: %s",
                        exc,
                    )

            # --- 6. write cross-process sentinel (no TTL — permanent) ---
            await lock_client.set(_SETUP_DONE_KEY, "1")
            _setup_done = True
            logger.info("[checkpointer] _setup_done=True, sentinel written to Redis")

        finally:
            # --- 7. always release the lock ---
            await lock.release()

        # --- 8. post-lock safety check ---
        sentinel = await lock_client.exists(_SETUP_DONE_KEY)
        if not sentinel:
            raise RuntimeError(
                f"[checkpointer] lock released but sentinel {_SETUP_DONE_KEY!r} "
                "not found in Redis — setup did not complete successfully"
            )
        if not _setup_done:
            raise RuntimeError(
                "[checkpointer] lock released but _setup_done is False — "
                "setup did not complete successfully"
            )

    finally:
        await lock_client.aclose()


@asynccontextmanager
async def checkpointer() -> AsyncGenerator[AsyncPostgresSaver, None]:
    """Async context manager that yields a ready-to-use AsyncPostgresSaver."""
    settings = get_settings()
    conn = await AsyncConnection.connect(
        settings.DATABASE_PG_URL,
        connect_timeout=settings.DB_CONNECT_TIMEOUT_SECONDS,
        autocommit=True,
        prepare_threshold=0,
        row_factory=dict_row,
        options="-csearch_path=fin_agents",
    )
    try:
        yield AsyncPostgresSaver(conn)
    finally:
        await conn.close()
