"""backend.db.redis.session.thread_user_store -- thread-to-user mapping cache.

Caches ``thread_id -> user_id`` in Redis (shard 0, control plane) so the
``has_app_viewers`` presence check can resolve the owning user without
a DB round-trip on every SSE publish.

The cache is populated once at query-submission time and expires after 24 h
(matching Centrifugo's ``history_ttl``).  If the Redis entry is missing the
helper falls back to a DB lookup and re-populates the cache.
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

_KEY_PREFIX = "fin:thread:user:"
_TTL = 86400  # 24 h


def _key(thread_id: str) -> str:
    return f"{_KEY_PREFIX}{thread_id}"


async def set_thread_user(thread_id: str, user_id: str) -> None:
    """Cache the *user_id* that owns *thread_id* on Redis shard 0.

    Args:
        thread_id: LangGraph thread UUID.
        user_id:   String UUID of the owning user.
    """
    from backend.db.redis.client import get_client

    try:
        redis = await get_client(shard=0)
        await redis.set(_key(thread_id), user_id, ex=_TTL)
    except Exception as exc:  # noqa: BLE001
        logger.error(
            "[thread_user_store] set failed thread_id=%s user_id=%s: %s",
            thread_id, user_id, exc,
        )


async def get_user_id_for_thread(thread_id: str) -> str | None:
    """Return the *user_id* for *thread_id*, using Redis cache then DB fallback.

    Args:
        thread_id: LangGraph thread UUID.

    Returns:
        User UUID string, or ``None`` if the thread is not found.
    """
    from backend.db.redis.client import get_client

    try:
        redis = await get_client(shard=0)
        cached = await redis.get(_key(thread_id))
        if cached:
            return cached if isinstance(cached, str) else cached.decode()
    except Exception as exc:  # noqa: BLE001
        logger.error(
            "[thread_user_store] Redis GET failed thread_id=%s: %s",
            thread_id, exc,
        )

    # DB fallback
    try:
        from backend.db.postgres.connection import raw_conn

        async with raw_conn(readonly=True) as conn:
            cur = await conn.execute(
                "SELECT user_id FROM fin_agents.user_queries WHERE thread_id = %s LIMIT 1",
                (thread_id,),
            )
            row = await cur.fetchone()

        if row and row["user_id"]:
            user_id: str = str(row["user_id"])
            # Re-populate cache for future calls.
            await set_thread_user(thread_id, user_id)
            return user_id
    except Exception as exc:  # noqa: BLE001
        logger.error(
            "[thread_user_store] DB fallback failed thread_id=%s: %s",
            thread_id, exc,
        )

    return None


__all__ = ["set_thread_user", "get_user_id_for_thread"]
