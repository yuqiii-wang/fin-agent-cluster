"""Pipeline: Compute industry-level performance stats.

Transform: fin_markets.securities + security_trade_stat_aggregs → industry_stats → industry_stat_aggregs
"""

import logging
from decimal import Decimal
from typing import Any

from app.pipelines.base import BasePipeline

logger = logging.getLogger(__name__)


class ComputeIndustryStatsPipeline(BasePipeline):
    """Compute industry_stats and industry_stat_aggregs from constituent security data."""

    async def run(self, region: str = "United States", **kwargs: Any) -> int:
        """Compute industry stats for all GICS sectors in a region.

        Args:
            region: Geographic region (default 'United States').

        Returns:
            Number of industry stat rows created.
        """
        try:
            # Get distinct industries with active securities
            industries = await self._execute(
                """
                SELECT DISTINCT industry
                FROM fin_markets.securities
                WHERE region = %s AND industry IS NOT NULL AND is_active = TRUE
                """,
                (region,),
            )

            count = 0
            for row in industries:
                industry = row["industry"]

                # Aggregate latest returns for all securities in the industry
                stats = await self._execute(
                    """
                    SELECT
                        COUNT(*) AS sec_count,
                        AVG(sta.interval_return) AS avg_return,
                        AVG(sta.rsi_14) AS avg_rsi,
                        AVG(sta.volatility_20d) AS avg_vol,
                        SUM(CASE WHEN sta.interval_return > 0 THEN 1 ELSE 0 END)::FLOAT
                            / NULLIF(COUNT(*), 0) AS breadth
                    FROM fin_markets.securities s
                    JOIN LATERAL (
                        SELECT interval_return, rsi_14, volatility_20d
                        FROM fin_markets.security_trade_stat_aggregs
                        WHERE security_id = s.id
                        ORDER BY published_at DESC LIMIT 1
                    ) sta ON TRUE
                    WHERE s.industry = %s AND s.region = %s AND s.is_active = TRUE
                    """,
                    (industry, region),
                )

                if not stats or stats[0]["sec_count"] == 0:
                    continue

                s = stats[0]
                avg_return = s["avg_return"]
                breadth = s["breadth"]

                # Insert industry_stats
                is_rows = await self._execute(
                    """
                    INSERT INTO fin_markets.industry_stats
                        (industry, region, published_at, breadth_pct)
                    VALUES (%s, %s, NOW(), %s)
                    ON CONFLICT (industry, region, published_at) DO UPDATE SET
                        breadth_pct = EXCLUDED.breadth_pct
                    RETURNING id
                    """,
                    (industry, region, Decimal(str(round(breadth, 4))) if breadth else None),
                )

                if is_rows:
                    stat_id = is_rows[0]["id"]
                    await self._execute(
                        """
                        INSERT INTO fin_markets.industry_stat_aggregs
                            (industry_stat_id, published_at, avg_return, volatility_20d)
                        VALUES (%s, NOW(), %s, %s)
                        ON CONFLICT (industry_stat_id) DO UPDATE SET
                            avg_return = EXCLUDED.avg_return,
                            volatility_20d = EXCLUDED.volatility_20d
                        """,
                        (stat_id,
                         Decimal(str(round(avg_return, 6))) if avg_return else None,
                         Decimal(str(round(s["avg_vol"], 6))) if s["avg_vol"] else None),
                    )
                    count += 1

            logger.info("Computed %d industry stats for %s", count, region)
            return count

        finally:
            await self.close()
