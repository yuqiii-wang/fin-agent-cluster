"""Pipeline: Ingest fundamentals from FMP → fin_markets.security_exts + security_ext_aggregs.

Transform: FMP key-metrics + ratios → security_exts → security_ext_aggregs
"""

import logging
from typing import Any

from app.pipelines.base import BasePipeline
from app.quant_api.fmp import FMPClient
from app.quant_api.transforms import fmp_metrics_to_security_ext, fmp_metrics_to_ext_aggreg

logger = logging.getLogger(__name__)


class ComputeFundamentalsPipeline(BasePipeline):
    """Fetch fundamentals from FMP and populate security_exts + security_ext_aggregs."""

    async def run(self, symbol: str, **kwargs: Any) -> dict[str, int]:
        """Ingest fundamentals for a symbol.

        Args:
            symbol: Ticker symbol.

        Returns:
            Dict with counts: {'security_exts': N, 'ext_aggregs': N}.
        """
        settings = self._settings
        fmp = FMPClient(api_key=settings.FMP_API_KEY)

        try:
            rows = await self._execute(
                "SELECT id FROM fin_markets.securities WHERE ticker = %s LIMIT 1",
                (symbol,),
            )
            if not rows:
                logger.error("Security not found for %s", symbol)
                return {"security_exts": 0, "ext_aggregs": 0}
            security_id = rows[0]["id"]

            metrics = await fmp.get_key_metrics(symbol)
            ratios = await fmp.get_financial_ratios(symbol)

            if not metrics:
                logger.warning("No metrics for %s", symbol)
                return {"security_exts": 0, "ext_aggregs": 0}

            # Insert security_exts
            ext = fmp_metrics_to_security_ext(metrics, ratios, security_id)
            ext_rows = await self._execute(
                """
                INSERT INTO fin_markets.security_exts
                    (security_id, published_at, market_cap_usd, pe_ratio, pb_ratio,
                     net_margin, eps_ttm, revenue_ttm, debt_to_equity, dividend_yield)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (security_id, published_at) DO UPDATE SET
                    market_cap_usd = EXCLUDED.market_cap_usd,
                    pe_ratio = EXCLUDED.pe_ratio,
                    pb_ratio = EXCLUDED.pb_ratio
                RETURNING id
                """,
                (ext.security_id, ext.published_at, ext.market_cap_usd,
                 ext.pe_ratio, ext.pb_ratio, ext.net_margin,
                 ext.eps_ttm, ext.revenue_ttm, ext.debt_to_equity, ext.dividend_yield),
            )

            if not ext_rows:
                return {"security_exts": 1, "ext_aggregs": 0}

            security_ext_id = ext_rows[0]["id"]

            # Insert security_ext_aggregs
            aggreg = fmp_metrics_to_ext_aggreg(metrics, ratios, security_ext_id)
            await self._execute(
                """
                INSERT INTO fin_markets.security_ext_aggregs
                    (security_ext_id, published_at, pe_forward, ps_ratio, ev_ebitda,
                     peg_ratio, roe, roa, gross_margin, operating_margin)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (security_ext_id) DO UPDATE SET
                    pe_forward = EXCLUDED.pe_forward,
                    ps_ratio = EXCLUDED.ps_ratio,
                    ev_ebitda = EXCLUDED.ev_ebitda
                """,
                (aggreg.security_ext_id, aggreg.published_at, aggreg.pe_forward,
                 aggreg.ps_ratio, aggreg.ev_ebitda, aggreg.peg_ratio,
                 aggreg.roe, aggreg.roa, aggreg.gross_margin, aggreg.operating_margin),
            )

            return {"security_exts": 1, "ext_aggregs": 1}

        finally:
            await fmp.close()
            await self.close()
