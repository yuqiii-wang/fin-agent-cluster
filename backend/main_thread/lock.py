"""backend.main_thread.lock -- Redis-based thread ownership lock.

Each graph run is exclusively owned by one main thread (FastAPI instance).
The lock key maps a thread UUID to the owning instance's port, PID, and
fencing token.

Key format:       ``fin:thread:lock:{thread_id}``
Value:            JSON ``{"port": 8432, "pid": 12345, "token": 7}``
Fencing counter:  ``fin:thread:fencing:{thread_id}`` -- monotonically
                  increasing integer, incremented atomically on each lock
                  acquisition or steal.  The token in the lock value equals
                  the counter at acquisition time and is stored in every DB
                  write so stale (zombie) writes can be rejected by the DB
                  guard ``fencing_token = current_token``.
TTL:              ``THREAD_LOCK_TTL_SECONDS`` (default 60 s), renewed every
                  ``THREAD_LOCK_RENEW_INTERVAL_SECONDS`` (default 25 s) while
                  the graph is running.

Fix summary implemented here
-----------------------------
Fix 1 - CAS steal: ``steal_lock`` only overwrites when the stored owner
        matches the dead owner confirmed by the caller.  Two simultaneous
        steal attempts produce at most one winner.
Fix 5 - Fencing token: ``acquire_lock`` and ``steal_lock`` atomically
        increment a per-thread counter in the same Redis script that writes
        the lock, returning the new token so the graph run can stamp all its
        DB writes.

The shard for both the lock and fencing counter follows ``shard_for_thread``
so all per-thread key operations target the same Redis node.
"""

from __future__ import annotations

import logging
import os
from typing import TypedDict

logger = logging.getLogger(__name__)

_LOCK_KEY_PREFIX = "fin:thread:lock:"
_FENCING_KEY_PREFIX = "fin:thread:fencing:"

# ---------------------------------------------------------------------------
# Lua scripts
# ---------------------------------------------------------------------------

# Atomic acquire: returns the new fencing token if acquired, nil otherwise.
# Entire script is atomic (single-threaded Redis eval).
# KEYS[1] = lock key, KEYS[2] = fencing counter key
# ARGV[1] = port, ARGV[2] = pid, ARGV[3] = lock ttl_ms, ARGV[4] = counter ttl_s
_ACQUIRE_SCRIPT = """
local existing = redis.call('GET', KEYS[1])
if existing then
    return nil
end
local token = redis.call('INCR', KEYS[2])
redis.call('EXPIRE', KEYS[2], tonumber(ARGV[4]))
local owner = '{"port":' .. ARGV[1] .. ',"pid":' .. ARGV[2] .. ',"token":' .. token .. '}'
redis.call('SET', KEYS[1], owner, 'PX', tonumber(ARGV[3]))
return token
"""

# CAS steal: only overwrites when stored owner matches dead_port+dead_pid.
# Returns the new fencing token if stolen, nil if the CAS check fails
# (lock is gone or belongs to a different instance than expected).
# KEYS[1] = lock key, KEYS[2] = fencing counter key
# ARGV[1] = dead_port, ARGV[2] = dead_pid
# ARGV[3] = new_port,  ARGV[4] = new_pid
# ARGV[5] = lock ttl_ms, ARGV[6] = counter ttl_s
_STEAL_CAS_SCRIPT = """
local val = redis.call('GET', KEYS[1])
if not val then
    return nil
end
local ok, data = pcall(cjson.decode, val)
if ok and data['port'] == tonumber(ARGV[1]) and data['pid'] == tonumber(ARGV[2]) then
    local token = redis.call('INCR', KEYS[2])
    redis.call('EXPIRE', KEYS[2], tonumber(ARGV[6]))
    local owner = '{"port":' .. ARGV[3] .. ',"pid":' .. ARGV[4] .. ',"token":' .. token .. '}'
    redis.call('SET', KEYS[1], owner, 'PX', tonumber(ARGV[5]))
    return token
end
return nil
"""

# Atomic TTL renewal: only extends if caller's port+pid match.
# KEYS[1] = lock key; ARGV[1] = port, ARGV[2] = pid, ARGV[3] = ttl_ms
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

# Atomic release: only deletes if caller's port+pid match.
# KEYS[1] = lock key; ARGV[1] = port, ARGV[2] = pid
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


class OwnerInfo(TypedDict):
    """Lock owner identifier including the fencing token at acquisition time."""

    port: int
    pid: int
    token: int


# ---------------------------------------------------------------------------
# Key helpers
# ---------------------------------------------------------------------------

def _lock_key(thread_id: str) -> str:
    """Return the Redis key for the thread ownership lock."""
    return f"{_LOCK_KEY_PREFIX}{thread_id}"


def _fencing_key(thread_id: str) -> str:
    """Return the Redis key for the per-thread fencing counter."""
    return f"{_FENCING_KEY_PREFIX}{thread_id}"


def _lock_shard(thread_id: str) -> int:
    """Return the Redis shard index for this thread's lock and fencing keys."""
    from backend.db.redis import shard_for_thread
    return shard_for_thread(thread_id)


def this_owner() -> OwnerInfo:
    """Return the OwnerInfo for this main thread instance (token=0 placeholder).

    Uses ``FASTAPI_PORT`` (set per-instance by ``run.py``) as the canonical
    instance address.  The real fencing token is returned by :func:`acquire_lock`
    or :func:`steal_lock` and stored separately via the context module.
    """
    from backend.config import get_settings
    return OwnerInfo(port=get_settings().FASTAPI_PORT, pid=os.getpid(), token=0)


async def _client(thread_id: str):  # type: ignore[return]
    from backend.db.redis import get_client
    return await get_client(_lock_shard(thread_id))


# ---------------------------------------------------------------------------
# Lock operations
# ---------------------------------------------------------------------------

async def acquire_lock(thread_id: str) -> int | None:
    """Try to acquire the thread lock atomically (Fix 5: increments fencing counter).

    Uses a Lua script that atomically checks for an existing lock, increments
    the per-thread fencing counter, and writes the lock with the new token.
    No two concurrent callers can both succeed.

    Args:
        thread_id: LangGraph thread UUID.

    Returns:
        The new fencing token (>= 1) if the lock was acquired, ``None`` if
        the lock is already held by another instance.
    """
    from backend.config import get_settings
    settings = get_settings()
    client = await _client(thread_id)
    owner = this_owner()
    ttl_ms = settings.THREAD_LOCK_TTL_SECONDS * 1000
    counter_ttl_s = settings.THREAD_LOCK_TTL_SECONDS * 20
    result = await client.eval(
        _ACQUIRE_SCRIPT, 2,
        _lock_key(thread_id), _fencing_key(thread_id),
        owner["port"], owner["pid"], ttl_ms, counter_ttl_s,
    )
    return int(result) if result is not None else None


async def steal_lock(thread_id: str, dead_owner: OwnerInfo) -> int | None:
    """CAS steal the lock from a confirmed-dead owner (Fix 1 + Fix 5).

    Atomically checks that the stored owner matches *dead_owner* (port+pid),
    then increments the fencing counter and overwrites the lock with the new
    owner.  If the stored owner no longer matches (another instance already
    stole it), returns ``None`` without writing anything.

    Args:
        thread_id:  LangGraph thread UUID.
        dead_owner: The owner previously confirmed dead by
            :func:`check_owner_alive`.  The CAS comparison uses port+pid.

    Returns:
        The new fencing token if the steal succeeded, ``None`` if the CAS
        check failed (lock was already stolen by someone else or expired).
    """
    from backend.config import get_settings
    settings = get_settings()
    client = await _client(thread_id)
    new_owner = this_owner()
    ttl_ms = settings.THREAD_LOCK_TTL_SECONDS * 1000
    counter_ttl_s = settings.THREAD_LOCK_TTL_SECONDS * 20
    result = await client.eval(
        _STEAL_CAS_SCRIPT, 2,
        _lock_key(thread_id), _fencing_key(thread_id),
        dead_owner["port"], dead_owner["pid"],
        new_owner["port"], new_owner["pid"],
        ttl_ms, counter_ttl_s,
    )
    if result is not None:
        token = int(result)
        logger.error(
            "[main_thread.lock] stolen lock thread_id=%s new_owner_port=%d fencing_token=%d",
            thread_id, new_owner["port"], token,
        )
        return token
    return None


async def get_lock_owner(thread_id: str) -> OwnerInfo | None:
    """Return the current lock owner, or ``None`` if the lock is not held.

    Backward-compatible: old lock values without a ``token`` field default
    to ``token=0``.

    Args:
        thread_id: LangGraph thread UUID.

    Returns:
        :class:`OwnerInfo` dict or ``None``.
    """
    import json
    client = await _client(thread_id)
    data = await client.get(_lock_key(thread_id))
    if data is None:
        return None
    try:
        raw = json.loads(data)
        return OwnerInfo(
            port=int(raw.get("port", 0)),
            pid=int(raw.get("pid", 0)),
            token=int(raw.get("token", 0)),
        )
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


def _pid_alive(pid: int) -> bool:
    """Return ``True`` if process *pid* is still running (Linux / WSL2).

    Uses ``os.kill(pid, 0)`` which sends no signal but raises
    ``ProcessLookupError`` if the PID does not exist and ``PermissionError``
    if the PID exists but is owned by another user.
    """
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True  # PID exists; we just cannot signal it.
    except OSError:
        return False


async def check_owner_alive(owner: OwnerInfo) -> bool:
    """Check whether the lock owner FastAPI instance is still running.

    Two-step check to handle the same-port restart race:
    1. TCP connect -- if the port is not responding at all, the instance is dead.
    2. PID check via ``os.kill(pid, 0)`` -- if the port IS responding but the
       recorded PID no longer exists, a new process replaced the old one on
       the same port (e.g. uvicorn ``--reload`` or process restart).  In that
       case we return ``False`` so the caller can steal the lock and dispatch
       recovery rather than routing to the replacement process.

    Args:
        owner: :class:`OwnerInfo` as stored in the lock.

    Returns:
        ``True`` only when both the port responds AND the original PID is alive.
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
        # Port is reachable -- verify the ORIGINAL process is still running.
        # Without this check, a replacement process on the same port would
        # cause the old dead owner to appear alive and prevent recovery.
        return _pid_alive(owner["pid"])
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
