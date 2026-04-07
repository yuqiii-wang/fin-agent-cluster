"""External resource cache — logs every quant API / web call to fin_agents.external_resources.

In DEBUG mode, the same ``cache_key`` is returned from the DB within the TTL
(default 1 hour) instead of hitting the external API again.
"""

import hashlib
import json
import logging
from datetime import datetime, timedelta, timezone
from typing import Any

from psycopg import AsyncConnection

logger = logging.getLogger(__name__)

# Default TTL for cached external responses
_DEFAULT_TTL_HOURS: float = 1.0


def make_cache_key(source: str, method: str, input_data: dict[str, Any]) -> str:
    """Build a deterministic SHA-256 cache key from source, method, and input.

    Args:
        source: Provider name (e.g. ``'fmp'``, ``'yfinance'``).
        method: API method name (e.g. ``'get_company_profile'``).
        input_data: Serialisable dict of call parameters.

    Returns:
        64-character lowercase hex SHA-256 digest.
    """
    raw = json.dumps(
        {"source": source, "method": method, "input": input_data},
        sort_keys=True,
        default=str,
    )
    return hashlib.sha256(raw.encode()).hexdigest()


async def get_cached(
    conn: AsyncConnection,
    cache_key: str,
    ttl_hours: float = _DEFAULT_TTL_HOURS,
) -> Any | None:
    """Return cached output for *cache_key* if a record exists within *ttl_hours*.

    Args:
        conn: Open psycopg async connection.
        cache_key: SHA-256 key produced by :func:`make_cache_key`.
        ttl_hours: How many hours back to look for a valid cached record.

    Returns:
        The stored ``output`` JSONB value, or ``None`` on cache miss.
    """
    cutoff = datetime.now(tz=timezone.utc) - timedelta(hours=ttl_hours)
    async with conn.cursor() as cur:
        await cur.execute(
            """
            SELECT output FROM fin_agents.external_resources
            WHERE cache_key = %s AND created_at >= %s
            ORDER BY created_at DESC
            LIMIT 1
            """,
            (cache_key, cutoff),
        )
        row = await cur.fetchone()
    if row:
        logger.debug("Cache hit for key=%s", cache_key[:16])
        return row[0]
    return None


async def log_external(
    conn: AsyncConnection,
    thread_id: str | None,
    node_name: str,
    source: str,
    method: str,
    input_data: dict[str, Any],
    output_data: Any,
    cache_key: str,
) -> None:
    """Insert a row into fin_agents.external_resources.

    Failures are swallowed with a warning so they never break the main call path.

    Args:
        conn: Open psycopg async connection.
        thread_id: LangGraph thread id (nullable).
        node_name: Graph node that triggered the call.
        source: Provider name (e.g. ``'fmp'``).
        method: API method name (e.g. ``'get_company_profile'``).
        input_data: Serialisable call parameters.
        output_data: Raw API response.
        cache_key: SHA-256 key from :func:`make_cache_key`.
    """
    try:
        output_json = json.dumps(output_data, default=str)
        input_json = json.dumps(input_data, default=str)
        async with conn.cursor() as cur:
            await cur.execute(
                """
                INSERT INTO fin_agents.external_resources
                    (thread_id, node_name, source, method, cache_key, input, output)
                VALUES (%s, %s, %s, %s, %s, %s::jsonb, %s::jsonb)
                """,
                (thread_id, node_name, source, method, cache_key, input_json, output_json),
            )
        logger.debug(
            "Logged external call source=%s method=%s cache_key=%s", source, method, cache_key[:16]
        )
    except Exception as exc:
        logger.warning("Failed to log external resource to DB: %s", exc)
