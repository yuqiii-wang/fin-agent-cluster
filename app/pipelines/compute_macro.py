"""Pipeline: Ingest macro economic data from FMP.

Transform: FMP economic API → fin_markets.macro_economics → macro_economics_stats → macro_dynamics
"""

import json
import logging
from decimal import Decimal
from typing import Any

from app.pipelines.base import BasePipeline
from app.quant_api.fmp import FMPClient
from app.quant_api.transforms import fmp_economic_to_macro

logger = logging.getLogger(__name__)

# Standard macro indicators to ingest
MACRO_INDICATORS = [
    "GDP",
    "realGDP",
    "nominalPotentialGDP",
    "consumerSentiment",
    "retailSales",
    "durableGoods",
    "unemploymentRate",
    "nonfarmPayroll",
    "CPI",
    "federalFundsRate",
    "industrialProductionTotalIndex",
    "housingStarts",
]


class ComputeMacroPipeline(BasePipeline):
    """Ingest macro indicators from FMP and compute stats/dynamics."""

    async def run(self, indicators: list[str] | None = None, **kwargs: Any) -> dict[str, int]:
        """Ingest macro data and compute derived tables.

        Args:
            indicators: List of indicator names (default: MACRO_INDICATORS).

        Returns:
            Dict with counts: {'macro_economics': N, 'macro_dynamics': N}.
        """
        indicators = indicators or MACRO_INDICATORS
        settings = self._settings
        fmp = FMPClient(api_key=settings.FMP_API_KEY)
        macro_count = 0
        dynamics_count = 0

        try:
            for indicator in indicators:
                data = await fmp.get_economic_indicators(indicator)
                if not data:
                    logger.warning("No data for indicator %s", indicator)
                    continue

                for item in data:
                    rec = fmp_economic_to_macro(item, indicator)
                    await self._execute(
                        """
                        INSERT INTO fin_markets.macro_economics
                            (indicator_name, region, published_at, value, extra)
                        VALUES (%s, %s, %s, %s, %s::jsonb)
                        ON CONFLICT (indicator_name, region, published_at) DO NOTHING
                        """,
                        (rec.indicator_name, rec.region, rec.published_at,
                         rec.value, json.dumps(rec.extra)),
                    )
                    macro_count += 1

                # Compute period-over-period dynamics
                recent = await self._execute(
                    """
                    SELECT id, published_at, value
                    FROM fin_markets.macro_economics
                    WHERE indicator_name = %s
                    ORDER BY published_at DESC
                    LIMIT 12
                    """,
                    (indicator,),
                )

                if len(recent) >= 2:
                    curr = float(recent[0]["value"])
                    prev = float(recent[1]["value"])
                    change_pct = ((curr - prev) / abs(prev)) * 100 if prev != 0 else None

                    await self._execute(
                        """
                        INSERT INTO fin_markets.macro_dynamics
                            (macro_economics_id, published_at, period_change_pct)
                        VALUES (%s, %s, %s)
                        ON CONFLICT (macro_economics_id) DO UPDATE SET
                            period_change_pct = EXCLUDED.period_change_pct
                        """,
                        (recent[0]["id"], recent[0]["published_at"],
                         Decimal(str(round(change_pct, 4))) if change_pct is not None else None),
                    )
                    dynamics_count += 1

            logger.info("Ingested %d macro rows, %d dynamics", macro_count, dynamics_count)
            return {"macro_economics": macro_count, "macro_dynamics": dynamics_count}

        finally:
            await fmp.close()
            await self.close()
