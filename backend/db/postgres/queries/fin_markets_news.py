"""News-related SQL templates for the ``fin_markets`` schema.

Covers ``fin_markets.news_stats`` (enriched per-article table) and
``fin_markets.news_topics`` (static topic taxonomy).  Raw news responses are
cached in the unified ``fin_markets.input_raw`` table (see ``InputRawSQL``).

All constants are raw SQL strings ready for use with psycopg3 ``%s``
parameterisation.
"""

from __future__ import annotations


class NewsStatsSQL:
    """Queries against ``fin_markets.news_stats`` (enriched per-article table)."""

    UPSERT = """
        INSERT INTO fin_markets.news_stats (
            input_raw_id, source, symbol, url, url_hash, title, content, source_name, published_at,
            summary, summary_embedding,
            sentiment_level, topic,
            tags
        ) VALUES (
            %s, %s, %s, %s, %s, %s, %s, %s, %s,
            %s, %s::vector,
            %s, %s,
            %s
        )
        ON CONFLICT (source, url_hash) DO UPDATE SET
            input_raw_id      = COALESCE(EXCLUDED.input_raw_id,      fin_markets.news_stats.input_raw_id),
            url               = COALESCE(EXCLUDED.url,               fin_markets.news_stats.url),
            content           = COALESCE(EXCLUDED.content,           fin_markets.news_stats.content),
            summary           = COALESCE(EXCLUDED.summary,           fin_markets.news_stats.summary),
            summary_embedding = COALESCE(EXCLUDED.summary_embedding, fin_markets.news_stats.summary_embedding),
            sentiment_level   = COALESCE(EXCLUDED.sentiment_level,   fin_markets.news_stats.sentiment_level),
            topic             = COALESCE(EXCLUDED.topic,             fin_markets.news_stats.topic),
            tags              = CASE
                                    WHEN array_length(EXCLUDED.tags, 1) > 0
                                    THEN EXCLUDED.tags
                                    ELSE fin_markets.news_stats.tags
                                END
    """

    GET_RECENT_BY_SYMBOL = """
        SELECT id, title, sentiment_level, published_at
        FROM fin_markets.news_stats
        WHERE symbol = %s
        ORDER BY published_at DESC
        LIMIT %s
    """

    GET_BY_INPUT_RAW_ID = """
        SELECT id, title, url, source, source_name, published_at,
               sentiment_level, topic,
               summary, tags, symbol
        FROM fin_markets.news_stats
        WHERE input_raw_id = %s
        ORDER BY published_at DESC NULLS LAST
    """

    GET_SUMMARIES_BY_INPUT_RAW_ID = """
        SELECT url_hash, summary, sentiment_level, topic, tags
        FROM fin_markets.news_stats
        WHERE input_raw_id = %s
          AND summary IS NOT NULL
    """

    GET_EMBEDDINGS_BY_INPUT_RAW_ID = """
        SELECT url_hash, summary_embedding::text AS summary_embedding
        FROM fin_markets.news_stats
        WHERE input_raw_id = %s
          AND summary_embedding IS NOT NULL
    """


class NewsTopicsSQL:
    """Queries against ``fin_markets.news_topics`` (static topic taxonomy)."""

    GET_ALL_CODES = """
        SELECT code
        FROM fin_markets.news_topics
        ORDER BY code
    """

    GET_ALL = """
        SELECT code, description
        FROM fin_markets.news_topics
        ORDER BY code
    """
