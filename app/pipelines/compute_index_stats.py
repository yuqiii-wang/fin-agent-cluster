"""Pipeline: Compute index stats from constituent data.

Transform: fin_markets.indexes + security_trades → index_stats → index_stat_aggregs
"""

import logging
from decimal import Decimal
from typing import Any

from app.pipelines.base import BasePipeline

logger = logging.getLogger(__name__)


class ComputeIndexStatsPipeline(BasePipeline):
    """Compute index_stats and index_stat_aggregs from constituent trade data."""

    async def run(self, index_id: int, **kwargs: Any) -> dict[str, int]:
        """Compute index-level statistics from constituent performance.

        Args:
            index_id: FK to fin_markets.indexes.

        Returns:
            Dict with counts: {'index_stats': N, 'index_stat_aggregs': N}.
        """
        try:
            # Get index info
            idx_rows = await self._execute(
                "SELECT security_id FROM fin_markets.indexes WHERE id = %s", (index_id,)
            )
            if not idx_rows:
                logger.error("Index not found: %d", index_id)
                return {"index_stats": 0, "index_stat_aggregs": 0}

            # Get latest constituent weights from index_2_security (most recent snapshot)
            constituents = await self._execute(
                """
                SELECT i2s.related_id AS security_id, i2s.weight_pct
                FROM fin_markets.index_2_security i2s
                JOIN fin_markets.index_stats ist ON ist.id = i2s.primary_id
                WHERE ist.index_id = %s
                ORDER BY ist.published_at DESC
                LIMIT 500
                """,
                (index_id,),
            )

            if not constituents:
                logger.warning("No constituents found for index %d", index_id)
                return {"index_stats": 0, "index_stat_aggregs": 0}

            # Compute weighted return from latest daily bars
            total_weight = Decimal(0)
            weighted_return = Decimal(0)
            returns_list: list[float] = []

            for c in constituents:
                sid = c["security_id"]
                weight = Decimal(str(c["weight_pct"])) if c["weight_pct"] else Decimal(0)

                stat_rows = await self._execute(
                    """
                    SELECT interval_return
                    FROM fin_markets.security_trade_stat_aggregs
                    WHERE security_id = %s
                    ORDER BY published_at DESC LIMIT 1
                    """,
                    (sid,),
                )
                if stat_rows and stat_rows[0]["interval_return"] is not None:
                    ret = Decimal(str(stat_rows[0]["interval_return"]))
                    weighted_return += weight * ret
                    total_weight += weight
                    returns_list.append(float(ret))

            if total_weight > 0:
                weighted_return = weighted_return / total_weight

            # Insert index_stats
            stat_rows = await self._execute(
                """
                INSERT INTO fin_markets.index_stats (index_id, published_at, base_value)
                VALUES (%s, NOW(), %s)
                RETURNING id
                """,
                (index_id, weighted_return),
            )
            stat_id = stat_rows[0]["id"] if stat_rows else None

            if stat_id:
                # Insert index_stat_aggregs
                pct_above = len([r for r in returns_list if r > 0]) / len(returns_list) * 100 if returns_list else None
                await self._execute(
                    """
                    INSERT INTO fin_markets.index_stat_aggregs
                        (index_stat_id, published_at, weighted_return, pct_above_sma_200)
                    VALUES (%s, NOW(), %s, %s)
                    ON CONFLICT (index_stat_id) DO UPDATE SET
                        weighted_return = EXCLUDED.weighted_return
                    """,
                    (stat_id, weighted_return, Decimal(str(round(pct_above, 4))) if pct_above else None),
                )

            return {"index_stats": 1, "index_stat_aggregs": 1 if stat_id else 0}

        finally:
            await self.close()
