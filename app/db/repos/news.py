"""NewsRepo — CRUD for fin_markets.news."""

import json
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.repos.base import BaseRepo
from app.models.markets.news import NewsRecord


class NewsRepo(BaseRepo):
    """Repository for fin_markets.news."""

    async def get_recent(
        self,
        symbol: str,
        hours: int = 6,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        """Return recent news articles for a symbol from the DB.

        First tries the ``news_ext_2_security`` relationship join; falls back
        to a title ``ILIKE`` heuristic if no linked articles exist.

        Args:
            symbol: Ticker symbol (e.g. ``'AAPL'``).
            hours: Look-back window in hours.
            limit: Maximum rows to return.

        Returns:
            List of news row dicts ordered by ``published_at`` descending.
        """
        rows = await self._execute(
            """
            SELECT n.*
            FROM fin_markets.news n
            JOIN fin_markets.news_ext_2_security r ON r.primary_id = n.id
            JOIN fin_markets.securities s          ON s.id = r.related_id
            WHERE s.ticker = :symbol
              AND n.published_at >= NOW() - make_interval(hours => :hours)
            ORDER BY n.published_at DESC
            LIMIT :limit
            """,
            {"symbol": symbol, "hours": hours, "limit": limit},
        )
        if rows:
            return rows

        # Fallback: title contains the ticker symbol
        return await self._execute(
            """
            SELECT *
            FROM fin_markets.news
            WHERE title ILIKE :pattern
              AND published_at >= NOW() - make_interval(hours => :hours)
            ORDER BY published_at DESC
            LIMIT :limit
            """,
            {"pattern": f"%{symbol}%", "hours": hours, "limit": limit},
        )

    async def upsert_news(self, rec: NewsRecord) -> None:
        """Insert a news article, ignoring duplicates on ``external_id``.

        Args:
            rec: ``NewsRecord`` to persist.
        """
        await self._execute(
            """
            INSERT INTO fin_markets.news
                (external_id, data_source, source_url, published_at,
                 title, body, extra)
            VALUES (:external_id, :data_source, :source_url, :published_at,
                    :title, :body, CAST(:extra AS jsonb))
            ON CONFLICT (external_id) DO NOTHING
            """,
            {
                "external_id": rec.external_id,
                "data_source": rec.data_source,
                "source_url": rec.source_url,
                "published_at": rec.published_at,
                "title": rec.title,
                "body": rec.body,
                "extra": json.dumps(rec.extra),
            },
        )
