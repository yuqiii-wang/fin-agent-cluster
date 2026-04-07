"""Pipeline: Ingest news from FMP API → fin_markets.news."""

import json
import logging
from typing import Any

from app.pipelines.base import BasePipeline
from app.quant_api.fmp import FMPClient
from app.quant_api.transforms import fmp_news_to_record

logger = logging.getLogger(__name__)


class IngestNewsPipeline(BasePipeline):
    """Fetch stock/market news from FMP and insert into fin_markets.news."""

    async def run(
        self,
        symbol: str | None = None,
        limit: int = 50,
        **kwargs: Any,
    ) -> int:
        """Ingest news articles, optionally filtered by symbol.

        Args:
            symbol: Optional ticker to filter news.
            limit: Maximum articles to fetch.

        Returns:
            Number of news records inserted.
        """
        settings = self._settings
        fmp = FMPClient(api_key=settings.FMP_API_KEY)

        try:
            articles = await fmp.get_stock_news(symbol=symbol, limit=limit)
            count = 0

            for article in articles:
                rec = fmp_news_to_record(article)
                await self._execute(
                    """
                    INSERT INTO fin_markets.news
                        (external_id, data_source, source_url, published_at, title, body, extra)
                    VALUES (%s, %s, %s, %s, %s, %s, %s::jsonb)
                    ON CONFLICT (external_id) DO NOTHING
                    """,
                    (rec.external_id, rec.data_source, rec.source_url,
                     rec.published_at, rec.title, rec.body, json.dumps(rec.extra)),
                )
                count += 1

            logger.info("Ingested %d news articles", count)
            return count

        finally:
            await fmp.close()
            await self.close()
