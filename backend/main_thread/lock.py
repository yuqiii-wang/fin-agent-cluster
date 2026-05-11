"""backend.main_thread.lock — Redis-based thread ownership lock.

Each graph run is exclusively owned by one main thread (FastAPI instance).
The lock key maps a thread UUID to the owning instance's port and PID.

Key format:  ``fin:thread:lock:{thread_id}``
Value:       JSON ``{"port": 8432, "pid": 12345}``
TTL:         ``THREAD_LOCK_TTL_SECONDS`` (default 60 s), renewed every
             ``THREAD_LOCK_RENEW_INTERVAL_SECONDS`` (default 25 s) while
             the graph is running.

The shard for the lock key follows the same ``shard_for_thread`` routing as
all other per-thread Redis data so lock operations never cross shards.
"""

from __future__ import annotations

import json
import logging
import os
from typing import TypedDict

logger = logging.getLogger(__name__)

_LOCK_KEY_PREFIX = "fin:thread:lock:"

# Lua script for atomic check-and-delete release:
# Only deletes if the caller's port+pid match the stored owner.
_RELEASE_SCRIPT = """
local val = redis.call('GET', KEYS[1])
if val then
    local ok, data = pcall(cjson.decode, val)
    if ok and data['port'] == tonumber(ARGV[1]) and data['pid'] == tonumber(ARGV[2]) then
        redis.call('DEL', KEYS[1])
        return 1
    end
end
return 0
"""

# Lua script for atomic check-and-pexpire renewal:
# Only extends TTL if the caller's port+pid match the stored owner.
_RENEW_SCRIPT = """
local val = redis.call('GET', KEYS[1])
if val then
    local ok, data = pcall(cjson.decode, val)
    if ok and data['port'] == tonumber(ARGV[1]) and data['pid'] == tonumber(ARGV[2]) then
        redis.call('PEXPIRE', KEYS[1], ARGV[3])
        return 1
    end
end
return 0
"""


class OwnerInfo(TypedDict):
    """Lock owner identifier."""

    port: int
    pid: int


def _lock_key(thread_id: str) -> str:
    """Return the Redis key for the thread ownership lock."""
    return f"{_LOCK_KEY_PREFIX}{thread_id}"


def _lock_shard(thread_id: str) -> int:
    """Return the Redis shard index for this thread's lock key."""
    from backend.db.redis import shard_for_thread
    return shard_for_thread(thread_id)


def this_owner() -> OwnerInfo:
    """Return the OwnerInfo for this main thread instance."""
    from backend.config import get_settings
    return OwnerInfo(port=get_settings().MAIN_THREAD_PORT, pid=os.getpid())


async def _client(thread_id: str):  # type: ignore[return]
    from backend.db.redis import get_client
    return await get_client(_lock_shard(thread_id))


async def acquire_lock(thread_id: str) -> bool:
    """Try to acquire the thread lock for this main thread instance (SET NX).

    Args:
        thread_id: LangGraph thread UUID.

    Returns:
        ``True`` if the lock was acquired, ``False`` if already held.
    """
    from backend.config import get_settings
    settings = get_settings()
    client = await _client(thread_id)
    owner = this_owner()
    value = json.dumps(owner)
    ttl_ms = settings.THREAD_LOCK_TTL_SECONDS * 1000
    result = await client.set(_lock_key(thread_id), value, px=ttl_ms, nx=True)
    return result is not None


async def steal_lock(thread_id: str) -> None:
    """Force-acquire the lock regardless of current owner.

    Must only be called after confirming the current owner is dead.

    Args:
        thread_id: LangGraph thread UUID.
    """
    from backend.config import get_settings
    settings = get_settings()
    client = await _client(thread_id)
    owner = this_owner()
    value = json.dumps(owner)
    ttl_ms = settings.THREAD_LOCK_TTL_SECONDS * 1000
    await client.set(_lock_key(thread_id), value, px=ttl_ms)
    logger.error(
        "[main_thread.lock] stolen lock thread_id=%s new_owner_port=%d",
        thread_id, owner["port"],
    )


async def get_lock_owner(thread_id: str) -> OwnerInfo | None:
    """Return the current lock owner, or ``None`` if the lock is not held.

    Args:
        thread_id: LangGraph thread UUID.

    Returns:
        :class:`OwnerInfo` dict or ``None``.
    """
    client = await _client(thread_id)
    data = await client.get(_lock_key(thread_id))
    if data is None:
        return None
    try:
        return json.loads(data)
    except Exception as exc:  # noqa: BLE001
        logger.error("[main_thread.lock] malformed lock value thread_id=%s: %s", thread_id, exc)
        return None


async def renew_lock(thread_id: str) -> bool:
    """Atomically extend the lock TTL if still owned by this instance.

    Args:
        thread_id: LangGraph thread UUID.

    Returns:
        ``True`` if TTL was extended, ``False`` if lock was lost or not held.
    """
    from backend.config import get_settings
    settings = get_settings()
    client = await _client(thread_id)
    owner = this_owner()
    ttl_ms = settings.THREAD_LOCK_TTL_SECONDS * 1000
    result = await client.eval(
        _RENEW_SCRIPT, 1, _lock_key(thread_id),
        owner["port"], owner["pid"], ttl_ms,
    )
    return bool(result)


async def release_lock(thread_id: str) -> None:
    """Atomically release the lock if owned by this instance.

    Args:
        thread_id: LangGraph thread UUID.
    """
    client = await _client(thread_id)
    owner = this_owner()
    await client.eval(
        _RELEASE_SCRIPT, 1, _lock_key(thread_id),
        owner["port"], owner["pid"],
    )


async def check_owner_alive(owner: OwnerInfo) -> bool:
    """Check whether the lock owner FastAPI instance is still reachable.

    Uses a plain TCP connection attempt to avoid importing an HTTP client.
    If the port is accepting connections, the process is alive.

    Args:
        owner: :class:`OwnerInfo` as stored in the lock.

    Returns:
        ``True`` if the TCP connection succeeds, ``False`` otherwise.
    """
    import asyncio
    from backend.config import get_settings

    timeout = get_settings().MAIN_THREAD_HEALTH_CHECK_TIMEOUT_SECONDS
    try:
        reader, writer = await asyncio.wait_for(
            asyncio.open_connection("127.0.0.1", owner["port"]),
            timeout=timeout,
        )
        writer.close()
        await writer.wait_closed()
        return True
    except Exception:  # noqa: BLE001
        return False


__all__ = [
    "OwnerInfo",
    "this_owner",
    "acquire_lock",
    "steal_lock",
    "get_lock_owner",
    "renew_lock",
    "release_lock",
    "check_owner_alive",
]
