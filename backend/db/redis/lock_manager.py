"""backend.db.redis.lock_manager -- async distributed Redis lock.

Provides :class:`RedisLock` -- a lightweight distributed lock backed by
Redis ``SET NX PX`` with optional automatic TTL renewal so a slow setup
operation does not lose the lock before it completes.
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import redis.asyncio as aioredis

logger = logging.getLogger(__name__)


class RedisLock:
    """Async distributed lock using Redis ``SET NX PX``.

    Args:
        client:           ``redis.asyncio.Redis`` instance.
        key:              Redis key for the lock.
        ttl:              Lock expiry in seconds.
        renewal_interval: Seconds between background TTL renewals (0 = disabled).
        parent_poll_interval: Unused; kept for API compatibility.
    """

    def __init__(
        self,
        client: "aioredis.Redis",
        key: str,
        *,
        ttl: int = 30,
        renewal_interval: float = 10.0,
        parent_poll_interval: float = 0.0,
    ) -> None:
        self._client = client
        self._key = key
        self._ttl = ttl
        self._renewal_interval = renewal_interval
        self._token: str | None = None
        self._renewal_task: asyncio.Task | None = None

    async def acquire(self) -> bool:
        """Try to acquire the lock.

        Returns:
            ``True`` if the lock was successfully acquired, ``False`` if it
            is already held by another caller.
        """
        token = str(uuid.uuid4())
        result = await self._client.set(
            self._key, token, nx=True, ex=self._ttl
        )
        if result is None:
            return False
        self._token = token
        if self._renewal_interval > 0:
            self._renewal_task = asyncio.create_task(self._renew_loop())
        return True

    async def release(self) -> None:
        """Release the lock if it is still held by this instance."""
        if self._renewal_task is not None:
            self._renewal_task.cancel()
            self._renewal_task = None

        if self._token is None:
            return

        # Only delete if the lock value matches our token (Lua atomic check-and-delete).
        script = """
        if redis.call("get", KEYS[1]) == ARGV[1] then
            return redis.call("del", KEYS[1])
        else
            return 0
        end
        """
        try:
            await self._client.eval(script, 1, self._key, self._token)  # type: ignore[attr-defined]
        except Exception as exc:  # noqa: BLE001
            logger.warning("[RedisLock] release error key=%s: %s", self._key, exc)
        finally:
            self._token = None

    async def _renew_loop(self) -> None:
        """Background task that periodically extends the lock TTL."""
        try:
            while True:
                await asyncio.sleep(self._renewal_interval)
                if self._token is None:
                    break
                current = await self._client.get(self._key)
                if current != self._token:
                    break
                await self._client.expire(self._key, self._ttl)
        except asyncio.CancelledError:
            pass
        except Exception as exc:  # noqa: BLE001
            logger.warning("[RedisLock] renewal error key=%s: %s", self._key, exc)


__all__ = ["RedisLock"]
