"""News-related SQL templates for the ``fin_markets`` schema.

Covers ``fin_markets.news_raw`` (news API cache) and
``fin_markets.news_stats`` (enriched per-article table).

All constants are raw SQL strings ready for use with psycopg3 ``%s``
parameterisation.
"""

from __future__ import annotations


class NewsRawSQL:
    """Queries against ``fin_markets.news_raw`` (news API cache)."""

    GET_CACHED = """
        SELECT output
        FROM fin_markets.news_raw
        WHERE cache_key = %s
          AND created_at > %s
        ORDER BY created_at DESC
        LIMIT 1
    """

    INSERT = """
        INSERT INTO fin_markets.news_raw
            (thread_id, node_name, source, method, cache_key, input, output)
        VALUES (%s, %s, %s, %s, %s, %s::jsonb, %s::jsonb)
    """

    INSERT_RETURNING = """
        INSERT INTO fin_markets.news_raw
            (thread_id, node_name, source, method, cache_key, input, output)
        VALUES (%s, %s, %s, %s, %s, %s::jsonb, %s::jsonb)
        RETURNING id
    """

    LIST_BY_SOURCE = """
        SELECT id, source, method, cache_key, created_at
        FROM fin_markets.news_raw
        WHERE source = %s
        ORDER BY created_at DESC
        LIMIT %s
    """

    PURGE_EXPIRED = """
        DELETE FROM fin_markets.news_raw
        WHERE created_at < NOW() - INTERVAL '4 hours'
    """


class NewsStatsSQL:
    """Queries against ``fin_markets.news_stats`` (enriched per-article table)."""

    UPSERT = """
        INSERT INTO fin_markets.news_stats (
            news_raw_id, source, symbol, url_hash, title, source_name, published_at,
            ai_summary, summary_embedding, sentiment_level,
            sector, topic_level1, topic_level2, impact_category,
            topics, region
        ) VALUES (
            %s, %s, %s, %s, %s, %s, %s, %s,
            %s,
            %s,
            %s,
            %s, %s, %s,
            %s, %s
        )
        ON CONFLICT (source, url_hash) DO UPDATE SET
            news_raw_id       = COALESCE(EXCLUDED.news_raw_id,       fin_markets.news_stats.news_raw_id),
            ai_summary        = COALESCE(EXCLUDED.ai_summary,        fin_markets.news_stats.ai_summary),
            summary_embedding = COALESCE(EXCLUDED.summary_embedding, fin_markets.news_stats.summary_embedding),
            sentiment_level   = COALESCE(EXCLUDED.sentiment_level,   fin_markets.news_stats.sentiment_level),
            sector            = COALESCE(EXCLUDED.sector,            fin_markets.news_stats.sector),
            topic_level1     = COALESCE(EXCLUDED.topic_level1,     fin_markets.news_stats.topic_level1),
            topic_level2     = COALESCE(EXCLUDED.topic_level2,     fin_markets.news_stats.topic_level2),
            impact_category   = COALESCE(EXCLUDED.impact_category,   fin_markets.news_stats.impact_category),
            region            = COALESCE(EXCLUDED.region,            fin_markets.news_stats.region),
            topics            = CASE
                                    WHEN array_length(EXCLUDED.topics, 1) > 0
                                    THEN EXCLUDED.topics
                                    ELSE fin_markets.news_stats.topics
                                END
    """

    GET_RECENT_BY_SYMBOL = """
        SELECT id, title, sentiment_level, sector, published_at
        FROM fin_markets.news_stats
        WHERE symbol = %s
        ORDER BY published_at DESC
        LIMIT %s
    """
