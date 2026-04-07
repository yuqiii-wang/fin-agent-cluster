"""Pipeline: Compute security risk scores.

Transform: fin_markets.security_exts + security_trade_stat_aggregs → security_risks
           fin_markets.industry_stats + industry_stat_aggregs → industry_risks
"""

import logging
from decimal import Decimal
from typing import Any

from app.pipelines.base import BasePipeline

logger = logging.getLogger(__name__)


class ComputeRisksPipeline(BasePipeline):
    """Compute security_risks and industry_risks from stats and fundamentals."""

    async def run(self, security_id: int | None = None, **kwargs: Any) -> dict[str, int]:
        """Compute risk scores for a specific security or all active securities.

        Args:
            security_id: Optional specific security. If None, process all active.

        Returns:
            Dict with counts: {'security_risks': N, 'industry_risks': N}.
        """
        try:
            sec_count = 0
            ind_count = 0

            if security_id:
                securities = [{"id": security_id}]
            else:
                securities = await self._execute(
                    "SELECT id FROM fin_markets.securities WHERE is_active = TRUE"
                )

            for sec in securities:
                sid = sec["id"]

                # Get latest trade stats
                stats = await self._execute(
                    """
                    SELECT id, volatility_20d, atr_14, price
                    FROM fin_markets.security_trade_stat_aggregs
                    WHERE security_id = %s ORDER BY published_at DESC LIMIT 1
                    """,
                    (sid,),
                )

                # Get latest fundamentals
                exts = await self._execute(
                    """
                    SELECT id, debt_to_equity, pe_ratio
                    FROM fin_markets.security_exts
                    WHERE security_id = %s ORDER BY published_at DESC LIMIT 1
                    """,
                    (sid,),
                )

                if not stats:
                    continue

                st = stats[0]
                ext = exts[0] if exts else {}

                # Simple composite risk score (0–100):
                # Weight: volatility (40%), VaR proxy (30%), leverage (20%), valuation (10%)
                vol_score = min(float(st["volatility_20d"] or 0) * 200, 40)  # vol=0.2 → score 40
                var_score = min(float(st["atr_14"] or 0) / max(float(st["price"] or 1), 0.01) * 300, 30)
                leverage_score = min(float(ext.get("debt_to_equity") or 0) * 5, 20)
                pe = float(ext.get("pe_ratio") or 15)
                val_score = min(abs(pe - 20) * 0.5, 10)  # deviation from PE=20

                risk_score = round(vol_score + var_score + leverage_score + val_score, 2)

                # VaR 95%: approximate as 1.65 * daily_vol
                daily_vol = float(st["volatility_20d"] or 0) / (365 ** 0.5)
                var_95 = round(1.65 * daily_vol, 6)

                await self._execute(
                    """
                    INSERT INTO fin_markets.security_risks
                        (security_id, published_at, security_ext_id, trade_stat_aggreg_id,
                         var_95, risk_score)
                    VALUES (%s, NOW(), %s, %s, %s, %s)
                    ON CONFLICT (security_id, published_at) DO UPDATE SET
                        var_95 = EXCLUDED.var_95,
                        risk_score = EXCLUDED.risk_score
                    """,
                    (sid, ext.get("id"), st["id"],
                     Decimal(str(var_95)), Decimal(str(risk_score))),
                )
                sec_count += 1

            # Industry risks (aggregate from security risks)
            industry_rows = await self._execute(
                """
                SELECT s.industry, s.region,
                       AVG(sr.risk_score) AS avg_risk,
                       MAX(sr.var_95) AS max_var
                FROM fin_markets.security_risks sr
                JOIN fin_markets.securities s ON s.id = sr.security_id
                WHERE s.industry IS NOT NULL AND s.region IS NOT NULL
                GROUP BY s.industry, s.region
                """
            )

            for ir in industry_rows:
                if ir["avg_risk"] is None:
                    continue
                await self._execute(
                    """
                    INSERT INTO fin_markets.industry_risks
                        (industry, region, published_at, var_95, risk_score)
                    VALUES (%s, %s, NOW(), %s, %s)
                    ON CONFLICT (industry, region, published_at) DO UPDATE SET
                        var_95 = EXCLUDED.var_95,
                        risk_score = EXCLUDED.risk_score
                    """,
                    (ir["industry"], ir["region"],
                     ir["max_var"], ir["avg_risk"]),
                )
                ind_count += 1

            logger.info("Computed %d security risks, %d industry risks", sec_count, ind_count)
            return {"security_risks": sec_count, "industry_risks": ind_count}

        finally:
            await self.close()
