"""Unified raw-input cache SQL templates for the ``fin_markets`` schema.

Covers ``fin_markets.input_raw`` — the single cache table that stores raw
external responses (news APIs, market-data/stats providers, fundamentals
endpoints, web fetches, …) or directly-injected payloads.  Each row carries
its own ``cache_ttl_seconds`` so freshness is evaluated per-entry.

All constants are raw SQL strings ready for use with psycopg3 ``%s``
parameterisation.
"""

from __future__ import annotations


class InputRawSQL:
    """Queries against ``fin_markets.input_raw`` (unified raw-input cache)."""

    GET_CACHED = """
        SELECT id, source, output, created_at
        FROM fin_markets.input_raw
        WHERE cache_key = %s
          AND created_at > NOW() - (cache_ttl_seconds * INTERVAL '1 second')
        ORDER BY created_at DESC
        LIMIT 1
    """

    INSERT = """
        INSERT INTO fin_markets.input_raw
            (thread_id, node_name, symbol, source, method, cache_key, cache_ttl_seconds, input, output)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s::jsonb, %s::jsonb)
    """

    INSERT_RETURNING = """
        INSERT INTO fin_markets.input_raw
            (thread_id, node_name, symbol, source, method, cache_key, cache_ttl_seconds, input, output)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s::jsonb, %s::jsonb)
        RETURNING id
    """

    GET_BY_ID = """
        SELECT id, symbol, source, method, output, created_at
        FROM fin_markets.input_raw
        WHERE id = %s
    """

    LIST_BY_SYMBOL = """
        SELECT id, source, method, symbol, created_at
        FROM fin_markets.input_raw
        WHERE symbol = %s
        ORDER BY created_at DESC
        LIMIT %s
    """

    EXPIRE_BY_THREAD_NODE = """
        UPDATE fin_markets.input_raw
        SET created_at = 'epoch'::timestamptz
        WHERE thread_id = %s
          AND node_name = %s
    """

    PURGE_EXPIRED = """
        DELETE FROM fin_markets.input_raw
        WHERE created_at < NOW() - (cache_ttl_seconds * INTERVAL '1 second')
    """


__all__ = ["InputRawSQL"]
