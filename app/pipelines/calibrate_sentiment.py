"""Pipeline: Run sentiment scale calibration.

Transform: fin_markets.security_trades → fin_strategies.sentiment_scale_calibration
                                        + fin_strategies.sentiment_numeric_bands

This is the Python wrapper around the SQL function:
  fin_strategies.calibrate_sentiment_scale(p_security_id, p_horizon_days, p_lookback_days)

It calls the DB-side function for each horizon.
"""

import logging
from typing import Any

from app.pipelines.base import BasePipeline

logger = logging.getLogger(__name__)

# Horizon label → natural (calendar) days mapping
HORIZON_DAYS = {
    "1d": 1,
    "1w": 7,
    "1m": 30,
    "3m": 90,
    "6m": 180,
    "1y": 360,
}


class CalibrateSentimentPipeline(BasePipeline):
    """Calibrate sentiment-to-numeric-return mapping for a security.

    Calls fin_strategies.calibrate_sentiment_scale() for each horizon:
    1d, 1w, 1m, 3m, 6m, 1y.
    """

    async def run(
        self,
        security_id: int,
        horizons: list[str] | None = None,
        lookback_days: int = 730,
        **kwargs: Any,
    ) -> dict[str, int | None]:
        """Run sentiment calibration for specified horizons.

        Args:
            security_id: FK to fin_markets.securities.
            horizons: List of horizon labels to calibrate (default: all 6).
            lookback_days: Calendar-day lookback window (default 730).

        Returns:
            Dict mapping horizon label → calibration_id (or None on failure).
        """
        horizons = horizons or list(HORIZON_DAYS.keys())
        results: dict[str, int | None] = {}

        try:
            for horizon in horizons:
                days = HORIZON_DAYS.get(horizon)
                if days is None:
                    logger.warning("Unknown horizon: %s", horizon)
                    results[horizon] = None
                    continue

                try:
                    rows = await self._execute(
                        "SELECT fin_strategies.calibrate_sentiment_scale(%s, %s, %s) AS cal_id",
                        (security_id, days, lookback_days),
                    )
                    cal_id = rows[0]["cal_id"] if rows else None
                    results[horizon] = cal_id
                    logger.info(
                        "Calibrated %s for security_id=%d → calibration_id=%s",
                        horizon, security_id, cal_id,
                    )
                except Exception as e:
                    logger.warning("Calibration failed for %s security_id=%d: %s", horizon, security_id, e)
                    results[horizon] = None

            return results

        finally:
            await self.close()
