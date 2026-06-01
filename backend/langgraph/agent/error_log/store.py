"""Redis-backed, per-thread error/warning log store.

Layout
------
For each thread the store keeps a single Redis hash::

    {AGENT_ERRLOG_KEY_PREFIX}{thread_id}
        <signature> -> JSON(level, logger, message, count, last_ts)

A normalized signature (see :mod:`.signature`) is the hash field, so duplicate
records collapse onto one field whose ``count`` is incremented atomically.  The
write path is a single Lua script so concurrent writers (the graph process and
Celery workers both target the same shard via :func:`shard_for_thread`) cannot
race, and a distinct-signature cap bounds memory without any time lag.

The store is written from a background thread (see :mod:`.handler`) and read by
``llm_orchestration_on_failure`` when composing a recovery decision.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone

from backend.config import get_settings
from backend.db.redis import get_client, shard_for_thread
from backend.langgraph.agent.error_log.errors import (
    ERRLOG_READ_FAILED,
    ERRLOG_WRITE_FAILED,
)
from backend.langgraph.agent.error_log.models import ThreadLogEntry

logger = logging.getLogger(__name__)

# Atomic upsert: create the field (respecting the distinct-entry cap) or bump an
# existing one's count and last_ts, then refresh the TTL.
#   KEYS[1] = hash key
#   ARGV[1] = signature        ARGV[2] = entry JSON (count placeholder = 1)
#   ARGV[3] = ttl seconds      ARGV[4] = max distinct entries
_UPSERT_LUA = """
local existing = redis.call('HGET', KEYS[1], ARGV[1])
if existing == false then
    if redis.call('HLEN', KEYS[1]) >= tonumber(ARGV[4]) then
        return 0
    end
    redis.call('HSET', KEYS[1], ARGV[1], ARGV[2])
else
    local entry = cjson.decode(existing)
    local fresh = cjson.decode(ARGV[2])
    fresh['count'] = (entry['count'] or 1) + 1
    redis.call('HSET', KEYS[1], ARGV[1], cjson.encode(fresh))
end
redis.call('EXPIRE', KEYS[1], tonumber(ARGV[3]))
return 1
"""


def _key(thread_id: str) -> str:
    """Return the Redis hash key for *thread_id*'s error-log store."""
    return f"{get_settings().AGENT_ERRLOG_KEY_PREFIX}{thread_id}"


async def record_thread_log(
    thread_id: str,
    *,
    signature: str,
    level: str,
    logger_name: str,
    message: str,
) -> None:
    """Upsert one captured log entry into *thread_id*'s store.

    Args:
        thread_id:   Owning LangGraph thread UUID.
        signature:   Dedup key from :func:`~.signature.make_signature`.
        level:       Log level name.
        logger_name: Logger that emitted the record.
        message:     Cleaned, truncated message text.
    """
    settings = get_settings()
    entry = {
        "level": level,
        "logger": logger_name,
        "message": message,
        "count": 1,
        "last_ts": datetime.now(timezone.utc).isoformat(),
    }
    try:
        client = await get_client(shard_for_thread(thread_id))
        await client.eval(
            _UPSERT_LUA,
            1,
            _key(thread_id),
            signature,
            json.dumps(entry, ensure_ascii=False),
            str(settings.AGENT_ERRLOG_TTL_SECONDS),
            str(settings.AGENT_ERRLOG_MAX_ENTRIES),
        )
    except Exception as exc:  # noqa: BLE001 — never let log capture raise
        logger.debug("[%s] thread=%s: %s", ERRLOG_WRITE_FAILED, thread_id, exc)


async def get_thread_logs(
    thread_id: str,
    *,
    limit: int | None = None,
) -> list[ThreadLogEntry]:
    """Return *thread_id*'s captured log entries, newest first.

    Each entry's message is already stored truncated to the configured
    per-entry character cap.

    Args:
        thread_id: Owning LangGraph thread UUID.
        limit:     Optional cap on the number of entries returned (newest by
                   ``last_ts``).  ``None`` returns all retained entries.

    Returns:
        List of :class:`ThreadLogEntry`, ordered by ``last_ts`` descending.
    """
    try:
        client = await get_client(shard_for_thread(thread_id))
        raw = await client.hgetall(_key(thread_id))
    except Exception as exc:  # noqa: BLE001
        logger.error("[%s] thread=%s: %s", ERRLOG_READ_FAILED, thread_id, exc)
        return []

    entries: list[ThreadLogEntry] = []
    for value in raw.values():
        try:
            entries.append(ThreadLogEntry.model_validate_json(value))
        except Exception as exc:  # noqa: BLE001
            logger.debug("[%s] thread=%s bad entry: %s", ERRLOG_READ_FAILED, thread_id, exc)

    entries.sort(key=lambda e: e.last_ts, reverse=True)
    return entries[:limit] if limit is not None else entries


__all__ = ["record_thread_log", "get_thread_logs"]
