"""backend.db.redis.router -- Redis shard URL router.

Provides :func:`get_redis_router` which returns a router capable of
mapping a shard index to the corresponding Redis URL.  Used by the
checkpointer setup and the Celery engine to target specific shards.
"""

from __future__ import annotations

from backend.config import get_settings


class RedisRouter:
    """Maps shard indices to Redis connection URLs.

    Falls back to ``DATABASE_REDIS_URL`` when no shard-specific node list is
    configured or the requested shard is out of range.
    """

    def __init__(self) -> None:
        settings = get_settings()
        self._nodes: list[str] = settings.DATABASE_REDIS_NODES or []
        self._fallback: str = settings.DATABASE_REDIS_URL

    def get_url_at(self, shard: int) -> str:
        """Return the Redis URL for *shard*.

        Args:
            shard: Zero-based shard index.

        Returns:
            Redis connection URL string.
        """
        if self._nodes and shard < len(self._nodes):
            return self._nodes[shard]
        return self._fallback

    def __len__(self) -> int:
        return max(len(self._nodes), 1)


_router: RedisRouter | None = None


def get_redis_router() -> RedisRouter:
    """Return the process-wide :class:`RedisRouter` singleton."""
    global _router
    if _router is None:
        _router = RedisRouter()
    return _router


__all__ = ["RedisRouter", "get_redis_router"]
