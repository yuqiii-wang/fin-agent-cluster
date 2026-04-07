"""Pipeline: Ingest OHLCV trades from FMP API → fin_markets.security_trades."""

import logging
from datetime import date
from typing import Any

from app.pipelines.base import BasePipeline
from app.quant_api.fmp import FMPClient
from app.quant_api.transforms import fmp_historical_to_trades

logger = logging.getLogger(__name__)


class IngestTradesPipeline(BasePipeline):
    """Fetch historical price bars from FMP and insert into fin_markets.security_trades."""

    async def run(
        self,
        symbol: str,
        from_date: date,
        to_date: date,
        interval: str = "1d",
        **kwargs: Any,
    ) -> int:
        """Ingest OHLCV bars for a symbol and date range.

        Args:
            symbol: Ticker symbol (e.g. 'AAPL').
            from_date: Start date (inclusive).
            to_date: End date (inclusive).
            interval: Bar interval code (default '1d').

        Returns:
            Number of trade records inserted.
        """
        settings = self._settings
        fmp = FMPClient(api_key=settings.FMP_API_KEY)

        try:
            # Resolve security_id
            rows = await self._execute(
                "SELECT id FROM fin_markets.securities WHERE ticker = %s LIMIT 1",
                (symbol,),
            )
            if not rows:
                logger.error("Security not found for symbol %s — ingest profile first", symbol)
                return 0
            security_id = rows[0]["id"]

            bars = await fmp.get_historical_prices(symbol, from_date, to_date, interval)
            if not bars:
                logger.warning("No price data returned for %s", symbol)
                return 0

            records = fmp_historical_to_trades(bars, security_id, interval)

            for rec in records:
                await self._execute(
                    """
                    INSERT INTO fin_markets.security_trades
                        (security_id, trade_date, interval, open, high, low, close, volume)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (security_id, trade_date, interval, start_time) DO NOTHING
                    """,
                    (rec.security_id, rec.trade_date, rec.interval,
                     rec.open, rec.high, rec.low, rec.close, rec.volume),
                )

            logger.info("Ingested %d trade bars for %s", len(records), symbol)
            return len(records)

        finally:
            await fmp.close()
            await self.close()
