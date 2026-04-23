"""Generic Redis distributed lock with auto-renewal and parent-task safety.

Implements a ``SET key value NX EX ttl`` leader lock, an asyncio renewal loop,
and a parent-task liveness guard that force-releases the lock when the owning
``asyncio.Task`` finishes unexpectedly without releasing via the normal
``async with`` exit.

Usage — async context manager (recommended)
-------------------------------------------
::

    async with RedisLock(redis_client, "lock:my_resource") as lock:
        if lock.acquired:
            # exclusive region
            ...
        # lock is always released on exit, even on exception / cancellation

Usage — manual acquire / release
---------------------------------
::

    lock = RedisLock(redis_client, "lock:my_resource")
    acquired = await lock.acquire()
    try:
        if acquired:
            ...
    finally:
        await lock.release()

Integration with parent asyncio.Task
-------------------------------------
Pass ``parent_task=asyncio.current_task()`` when constructing the lock so the
renewal coroutine polls the task every :attr:`RedisLock.parent_poll_interval`
seconds.  If the task is done but the lock was not released (e.g. a Redis
failure during ``__aexit__``), the renewer force-releases the key within one
poll interval, unblocking standby holders.

This is the single source of truth for all Redis distributed locks in this
project.  Module-specific lock keys and TTLs live in the calling modules.
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from typing import Optional

import redis.asyncio as aioredis

logger = logging.getLogger(__name__)


class RedisLock:
    """Async Redis distributed lock with auto-renewal and parent-task liveness guard.

    Attributes:
        key:                  Redis key for the lock.
        ttl:                  Lock TTL in seconds.  Must be > ``renewal_interval * 2``.
        renewal_interval:     Seconds between lock renewals while held.
        parent_poll_interval: Seconds between parent-task liveness checks in the
                              renewal loop.  Set to ``0`` to disable the guard.
        owner:                UUID string written as the lock value to prove ownership.
        acquired:             ``True`` once :meth:`acquire` returns successfully.
    """

    def __init__(
        self,
        client: aioredis.Redis,
        key: str,
        *,
        ttl: int = 30,
        renewal_interval: float = 12.0,
        parent_poll_interval: float = 60.0,
        parent_task: Optional[asyncio.Task] = None,
    ) -> None:
        """Initialise a lock instance (does not acquire yet).

        Args:
            client:               Connected ``redis.asyncio.Redis`` instance.
            key:                  Redis key, e.g. ``"lock:lifecycle_fanout"``.
            ttl:                  Lock expiry in seconds.
            renewal_interval:     How often (seconds) to renew the TTL.
            parent_poll_interval: How often (seconds) to check parent task liveness.
                                  Use ``0`` to disable the check.
            parent_task:          The asyncio Task that owns this lock.  Pass
                                  ``asyncio.current_task()`` from the calling coroutine.
                                  If ``None`` and ``parent_poll_interval > 0``, the
                                  guard is disabled automatically.
        """
        self._client = client
        self.key = key
        self.ttl = ttl
        self.renewal_interval = renewal_interval
        self.parent_poll_interval = parent_poll_interval
        self._parent_task = parent_task
        self.owner: str = str(uuid.uuid4())
        self.acquired: bool = False
        self._renewer: Optional[asyncio.Task] = None

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def acquire(self) -> bool:
        """Try once to acquire the lock (non-blocking).

        Returns:
            ``True`` if the lock was acquired, ``False`` if already held.
        """
        ok = await self._client.set(self.key, self.owner, nx=True, ex=self.ttl)
        self.acquired = bool(ok)
        if self.acquired:
            self._renewer = asyncio.create_task(
                self._renewal_loop(),
                name=f"redis-lock-renew:{self.key}",
            )
            logger.debug("[RedisLock] acquired key=%s owner=%s", self.key, self.owner)
        return self.acquired

    async def release(self) -> None:
        """Release the lock if this instance still owns it.

        Cancels the renewal task first, then deletes the Redis key only when
        the stored value matches :attr:`owner` (prevents releasing a lock that
        was re-acquired by another holder after an unexpected TTL expiry).
        """
        if self._renewer is not None and not self._renewer.done():
            self._renewer.cancel()
            try:
                await asyncio.wait_for(asyncio.shield(self._renewer), timeout=2.0)
            except (asyncio.CancelledError, asyncio.TimeoutError, Exception):
                pass
        if not self.acquired:
            return
        try:
            val = await self._client.get(self.key)
            if val == self.owner:
                await self._client.delete(self.key)
                logger.info("[RedisLock] released key=%s owner=%s", self.key, self.owner)
            else:
                logger.warning(
                    "[RedisLock] release_skipped — lock no longer owned key=%s owner=%s current=%s",
                    self.key,
                    self.owner,
                    val,
                )
        except Exception as exc:  # noqa: BLE001
            logger.warning("[RedisLock] release_error key=%s: %s", self.key, exc)
        finally:
            self.acquired = False

    # ------------------------------------------------------------------
    # Async context manager
    # ------------------------------------------------------------------

    async def __aenter__(self) -> "RedisLock":
        """Acquire the lock and return self."""
        await self.acquire()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:  # type: ignore[override]
        """Release the lock on exit regardless of exception type."""
        await self.release()

    # ------------------------------------------------------------------
    # Internal renewal loop
    # ------------------------------------------------------------------

    async def _renewal_loop(self) -> None:
        """Periodically renew TTL while holding the lock.

        Also polls the parent task for liveness every
        :attr:`parent_poll_interval` seconds.  If the parent is done but the
        lock was not released through the normal context-manager exit, the
        lock is force-released here so standby holders are not blocked.
        """
        parent_task = self._parent_task
        poll_guard = parent_task is not None and self.parent_poll_interval > 0
        poll_elapsed: float = 0.0

        while True:
            await asyncio.sleep(self.renewal_interval)
            poll_elapsed += self.renewal_interval

            try:
                # ── Parent-task liveness check ─────────────────────────
                if poll_guard and poll_elapsed >= self.parent_poll_interval:
                    poll_elapsed = 0.0
                    if parent_task.done():  # type: ignore[union-attr]
                        logger.warning(
                            "[RedisLock] parent_task_done — force-releasing lock key=%s owner=%s",
                            self.key,
                            self.owner,
                        )
                        try:
                            val = await self._client.get(self.key)
                            if val == self.owner:
                                await self._client.delete(self.key)
                                logger.info(
                                    "[RedisLock] force_released key=%s owner=%s",
                                    self.key,
                                    self.owner,
                                )
                        except Exception as rel_exc:  # noqa: BLE001
                            logger.warning(
                                "[RedisLock] force_release_error key=%s: %s",
                                self.key,
                                rel_exc,
                            )
                        self.acquired = False
                        return

                # ── Regular TTL renewal ────────────────────────────────
                val = await self._client.get(self.key)
                if val != self.owner:
                    logger.warning(
                        "[RedisLock] lock_lost key=%s owner=%s current=%s — stopping renewal",
                        self.key,
                        self.owner,
                        val,
                    )
                    self.acquired = False
                    return
                await self._client.expire(self.key, self.ttl)
                logger.debug("[RedisLock] renewed key=%s owner=%s", self.key, self.owner)

            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001
                logger.warning("[RedisLock] renewal_error key=%s: %s", self.key, exc)


__all__ = ["RedisLock"]
