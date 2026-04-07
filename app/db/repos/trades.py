"""TradeRepo — CRUD for fin_markets.security_trades."""

from datetime import date
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.repos.base import BaseRepo
from app.models.markets.trades import SecurityTradeRecord


class TradeRepo(BaseRepo):
    """Repository for fin_markets.security_trades."""

    async def is_covered(
        self,
        security_id: int,
        from_date: date,
        to_date: date,
        interval: str = "1d",
    ) -> bool:
        """Check whether the date range is already stored in security_trades.

        Uses a 35 % of calendar-days heuristic to account for weekends and
        market holidays.

        Args:
            security_id: FK to fin_markets.securities.
            from_date: Inclusive range start.
            to_date: Inclusive range end.
            interval: Bar interval code (default ``'1d'``).

        Returns:
            ``True`` if the range appears fully covered.
        """
        rows = await self._execute(
            """
            SELECT COUNT(*) AS cnt
            FROM fin_markets.security_trades
            WHERE security_id = :security_id
              AND interval    = :interval
              AND trade_date >= :from_date
              AND trade_date <= :to_date
            """,
            {
                "security_id": security_id,
                "interval": interval,
                "from_date": from_date,
                "to_date": to_date,
            },
        )
        if not rows:
            return False
        count = int(rows[0]["cnt"])
        calendar_days = (to_date - from_date).days + 1
        return count >= max(1, int(calendar_days * 0.35))

    async def get_trades(
        self,
        security_id: int,
        from_date: date,
        to_date: date,
        interval: str = "1d",
    ) -> list[dict[str, Any]]:
        """Return OHLCV bars for the given range from the DB.

        Args:
            security_id: FK to fin_markets.securities.
            from_date: Inclusive range start.
            to_date: Inclusive range end.
            interval: Bar interval code.

        Returns:
            List of row dicts ordered by ``trade_date`` ascending.
        """
        return await self._execute(
            """
            SELECT trade_date, open, high, low, close, volume
            FROM fin_markets.security_trades
            WHERE security_id = :security_id
              AND interval    = :interval
              AND trade_date >= :from_date
              AND trade_date <= :to_date
            ORDER BY trade_date
            """,
            {
                "security_id": security_id,
                "interval": interval,
                "from_date": from_date,
                "to_date": to_date,
            },
        )

    async def upsert_trade(self, rec: SecurityTradeRecord) -> None:
        """Insert a single OHLCV bar, ignoring duplicate (security_id, trade_date, interval).

        Args:
            rec: ``SecurityTradeRecord`` to persist.
        """
        await self._execute(
            """
            INSERT INTO fin_markets.security_trades
                (security_id, trade_date, interval, open, high, low, close, volume)
            VALUES (:security_id, :trade_date, :interval,
                    :open, :high, :low, :close, :volume)
            ON CONFLICT (security_id, trade_date, interval, start_time) DO NOTHING
            """,
            {
                "security_id": rec.security_id,
                "trade_date": rec.trade_date,
                "interval": rec.interval,
                "open": rec.open,
                "high": rec.high,
                "low": rec.low,
                "close": rec.close,
                "volume": rec.volume,
            },
        )
