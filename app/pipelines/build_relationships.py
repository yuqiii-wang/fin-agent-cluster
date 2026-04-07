"""Pipeline: Populate bridge/relationship tables.

Transform: Derive *_2_* bridge table rows from entity/security/news data.
  - news_ext_2_security
  - news_ext_2_entity
  - news_ext_2_industry
  - index_2_security (from FMP index constituents)
"""

import logging
from typing import Any

from app.pipelines.base import BasePipeline
from app.quant_api.fmp import FMPClient

logger = logging.getLogger(__name__)


class BuildRelationshipsPipeline(BasePipeline):
    """Populate bridge tables linking news, securities, entities, and indexes."""

    async def run(self, task: str = "all", **kwargs: Any) -> dict[str, int]:
        """Build relationship rows.

        Args:
            task: Which bridges to build — 'all', 'news', or 'index'.

        Returns:
            Dict with counts per bridge table.
        """
        results: dict[str, int] = {}
        try:
            if task in ("all", "news"):
                results.update(await self._build_news_bridges())
            if task in ("all", "index"):
                results.update(await self._build_index_bridges(**kwargs))
            return results
        finally:
            await self.close()

    async def _build_news_bridges(self) -> dict[str, int]:
        """Link news_exts to securities via ticker mentions in title/body.

        Returns:
            Counts of rows created per bridge table.
        """
        # Get unlinked news_exts
        unlinked = await self._execute(
            """
            SELECT ne.id AS ne_id, n.title, n.body
            FROM fin_markets.news_exts ne
            JOIN fin_markets.news n ON n.id = ne.news_id
            WHERE NOT EXISTS (
                SELECT 1 FROM fin_markets.news_ext_2_security nes
                WHERE nes.primary_id = ne.id
            )
            LIMIT 500
            """
        )

        # Get all active tickers for matching
        tickers = await self._execute(
            "SELECT id, ticker FROM fin_markets.securities WHERE is_active = TRUE"
        )
        ticker_map = {t["ticker"]: t["id"] for t in tickers}

        ne2s_count = 0
        for row in unlinked:
            text = f"{row['title'] or ''} {row['body'] or ''}"
            for ticker, sec_id in ticker_map.items():
                if len(ticker) < 2:
                    continue
                # Simple ticker-in-text matching (word boundary)
                if f" {ticker} " in f" {text} " or f"${ticker}" in text:
                    await self._execute(
                        """
                        INSERT INTO fin_markets.news_ext_2_security (primary_id, related_id)
                        VALUES (%s, %s)
                        ON CONFLICT DO NOTHING
                        """,
                        (row["ne_id"], sec_id),
                    )
                    ne2s_count += 1

        logger.info("Built %d news_ext_2_security links", ne2s_count)
        return {"news_ext_2_security": ne2s_count}

    async def _build_index_bridges(self, index_symbol: str = "sp500", **kwargs: Any) -> dict[str, int]:
        """Build index_2_security from FMP index constituents API.

        Args:
            index_symbol: Index identifier for FMP (e.g. 'sp500', 'dowjones').

        Returns:
            Count of rows created.
        """
        settings = self._settings
        fmp = FMPClient(api_key=settings.FMP_API_KEY)

        try:
            constituents = await fmp.get_index_constituents(index_symbol)
        finally:
            await fmp.close()

        if not constituents:
            return {"index_2_security": 0}

        # Find or create the index row
        idx_rows = await self._execute(
            """
            SELECT ist.id AS index_stat_id
            FROM fin_markets.indexes idx
            JOIN fin_markets.securities s ON s.id = idx.security_id
            JOIN fin_markets.index_stats ist ON ist.index_id = idx.id
            WHERE s.ticker = %s
            ORDER BY ist.published_at DESC LIMIT 1
            """,
            (index_symbol.upper(),),
        )

        if not idx_rows:
            logger.warning("Index %s not found in DB", index_symbol)
            return {"index_2_security": 0}

        index_stat_id = idx_rows[0]["index_stat_id"]

        count = 0
        for c in constituents:
            ticker = c.get("symbol")
            weight = c.get("weight")
            if not ticker:
                continue

            sec_rows = await self._execute(
                "SELECT id FROM fin_markets.securities WHERE ticker = %s LIMIT 1",
                (ticker,),
            )
            if not sec_rows:
                continue

            await self._execute(
                """
                INSERT INTO fin_markets.index_2_security (primary_id, related_id, weight_pct)
                VALUES (%s, %s, %s)
                ON CONFLICT (primary_id, related_id) DO UPDATE SET weight_pct = EXCLUDED.weight_pct
                """,
                (index_stat_id, sec_rows[0]["id"], weight),
            )
            count += 1

        logger.info("Built %d index_2_security links for %s", count, index_symbol)
        return {"index_2_security": count}
