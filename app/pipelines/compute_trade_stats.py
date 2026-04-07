"""Pipeline: Compute technical indicators from OHLCV trades.

Transform: fin_markets.security_trades → fin_markets.security_trade_stat_aggregs

Computes SMAs, EMAs, RSI, MACD, Bollinger bands, ATR, volume ratio, etc.
from raw OHLCV bars. This is the Python equivalent of the SQL schema's
pre-computed technical aggregates.
"""

import logging
from decimal import Decimal
from typing import Any

from app.pipelines.base import BasePipeline

logger = logging.getLogger(__name__)


class ComputeTradeStatsPipeline(BasePipeline):
    """Compute security_trade_stat_aggregs from security_trades OHLCV bars."""

    async def run(self, security_id: int, interval: str = "1d", **kwargs: Any) -> int:
        """Compute and upsert technical indicators for a security.

        Args:
            security_id: FK to fin_markets.securities.
            interval: Trade interval to process (default '1d').

        Returns:
            Number of stat rows upserted.
        """
        try:
            # Fetch all daily bars ordered by date
            bars = await self._execute(
                """
                SELECT trade_date, open, high, low, close, volume
                FROM fin_markets.security_trades
                WHERE security_id = %s AND interval = %s
                ORDER BY trade_date ASC
                """,
                (security_id, interval),
            )

            if len(bars) < 26:
                logger.warning("Not enough bars (%d) for security_id=%d", len(bars), security_id)
                return 0

            closes = [float(b["close"]) for b in bars]
            highs = [float(b["high"]) for b in bars]
            lows = [float(b["low"]) for b in bars]
            volumes = [int(b["volume"] or 0) for b in bars]
            dates = [b["trade_date"] for b in bars]

            count = 0
            for i in range(max(199, 25), len(bars)):
                window = closes[:i + 1]
                high_w = highs[:i + 1]
                low_w = lows[:i + 1]
                vol_w = volumes[:i + 1]

                price = closes[i]
                prev_close = closes[i - 1] if i > 0 else price
                interval_return = (price - prev_close) / prev_close if prev_close else None

                # SMAs
                sma_3 = _sma(window, 3)
                sma_7 = _sma(window, 7)
                sma_10 = _sma(window, 10)
                sma_20 = _sma(window, 20)
                sma_50 = _sma(window, 50)
                sma_200 = _sma(window, 200)

                # EMAs
                ema_12 = _ema(window, 12)
                ema_26 = _ema(window, 26)

                # MACD signal (9-period EMA of MACD line)
                macd_line = [_ema(window[:j + 1], 12) - _ema(window[:j + 1], 26)
                             for j in range(max(25, i - 8), i + 1)
                             if _ema(window[:j + 1], 12) is not None and _ema(window[:j + 1], 26) is not None]
                macd_signal = _sma_list(macd_line, 9) if len(macd_line) >= 9 else None

                # RSI
                rsi_14 = _rsi(window, 14)

                # ATR
                atr_14 = _atr(high_w, low_w, window, 14)

                # Bollinger
                bollinger_std = _std(window, 20)

                # Volume ratio
                avg_vol_20 = sum(vol_w[-20:]) / 20 if len(vol_w) >= 20 else None
                volume_ratio = volumes[i] / avg_vol_20 if avg_vol_20 and avg_vol_20 > 0 else None

                # Volatility
                vol_20d = _realized_vol(window, 20)

                # 52-week high/low (365 natural days)
                p52w_high = max(high_w[-365:]) if len(high_w) >= 365 else max(high_w)
                p52w_low = min(low_w[-365:]) if len(low_w) >= 365 else min(low_w)

                # Return lags
                r1d_lag = (closes[i - 1] - closes[i - 2]) / closes[i - 2] if i >= 2 and closes[i - 2] else None
                r2d_lag = (closes[i - 2] - closes[i - 3]) / closes[i - 3] if i >= 3 and closes[i - 3] else None
                r3d_lag = (closes[i - 3] - closes[i - 4]) / closes[i - 4] if i >= 4 and closes[i - 4] else None

                await self._execute(
                    """
                    INSERT INTO fin_markets.security_trade_stat_aggregs
                        (security_id, published_at, price, interval_return,
                         return_1d_lag, return_2d_lag, return_3d_lag,
                         sma_3, sma_7, sma_10, sma_20, sma_50, sma_200,
                         ema_12, ema_26, macd_signal,
                         rsi_14, atr_14, bollinger_std, volatility_20d,
                         volume_ratio, price_52w_high, price_52w_low)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (security_id, published_at) DO UPDATE SET
                        price = EXCLUDED.price,
                        interval_return = EXCLUDED.interval_return,
                        sma_3 = EXCLUDED.sma_3, sma_7 = EXCLUDED.sma_7,
                        sma_10 = EXCLUDED.sma_10, sma_20 = EXCLUDED.sma_20,
                        sma_50 = EXCLUDED.sma_50, sma_200 = EXCLUDED.sma_200,
                        ema_12 = EXCLUDED.ema_12, ema_26 = EXCLUDED.ema_26,
                        macd_signal = EXCLUDED.macd_signal,
                        rsi_14 = EXCLUDED.rsi_14, atr_14 = EXCLUDED.atr_14,
                        bollinger_std = EXCLUDED.bollinger_std,
                        volatility_20d = EXCLUDED.volatility_20d,
                        volume_ratio = EXCLUDED.volume_ratio,
                        price_52w_high = EXCLUDED.price_52w_high,
                        price_52w_low = EXCLUDED.price_52w_low
                    """,
                    (security_id, dates[i], _d(price), _d(interval_return),
                     _d(r1d_lag), _d(r2d_lag), _d(r3d_lag),
                     _d(sma_3), _d(sma_7), _d(sma_10), _d(sma_20), _d(sma_50), _d(sma_200),
                     _d(ema_12), _d(ema_26), _d(macd_signal),
                     _d(rsi_14), _d(atr_14), _d(bollinger_std), _d(vol_20d),
                     _d(volume_ratio), _d(p52w_high), _d(p52w_low)),
                )
                count += 1

            logger.info("Computed %d trade stat rows for security_id=%d", count, security_id)
            return count

        finally:
            await self.close()


# ── Technical indicator helpers ──────────────────────────────────────────────

def _d(v: float | None) -> Decimal | None:
    """Convert float to Decimal for DB insertion."""
    return Decimal(str(round(v, 6))) if v is not None else None


def _sma(data: list[float], period: int) -> float | None:
    """Simple Moving Average."""
    if len(data) < period:
        return None
    return sum(data[-period:]) / period


def _sma_list(data: list[float | None], period: int) -> float | None:
    """SMA over a pre-computed list (may have None entries)."""
    valid = [x for x in data[-period:] if x is not None]
    return sum(valid) / len(valid) if len(valid) >= period else None


def _ema(data: list[float], period: int) -> float | None:
    """Exponential Moving Average."""
    if len(data) < period:
        return None
    k = 2 / (period + 1)
    ema = sum(data[:period]) / period
    for price in data[period:]:
        ema = price * k + ema * (1 - k)
    return ema


def _rsi(data: list[float], period: int = 14) -> float | None:
    """Relative Strength Index (Wilder's smoothing)."""
    if len(data) < period + 1:
        return None
    deltas = [data[i] - data[i - 1] for i in range(1, len(data))]
    gains = [d if d > 0 else 0 for d in deltas]
    losses = [-d if d < 0 else 0 for d in deltas]

    avg_gain = sum(gains[:period]) / period
    avg_loss = sum(losses[:period]) / period

    for i in range(period, len(gains)):
        avg_gain = (avg_gain * (period - 1) + gains[i]) / period
        avg_loss = (avg_loss * (period - 1) + losses[i]) / period

    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))


def _atr(highs: list[float], lows: list[float], closes: list[float], period: int = 14) -> float | None:
    """Average True Range."""
    if len(closes) < period + 1:
        return None
    trs = []
    for i in range(1, len(closes)):
        tr = max(highs[i] - lows[i], abs(highs[i] - closes[i - 1]), abs(lows[i] - closes[i - 1]))
        trs.append(tr)
    if len(trs) < period:
        return None
    atr = sum(trs[:period]) / period
    for i in range(period, len(trs)):
        atr = (atr * (period - 1) + trs[i]) / period
    return atr


def _std(data: list[float], period: int) -> float | None:
    """Standard deviation over last N periods."""
    if len(data) < period:
        return None
    window = data[-period:]
    mean = sum(window) / period
    variance = sum((x - mean) ** 2 for x in window) / period
    return variance ** 0.5


def _realized_vol(data: list[float], period: int, annualize: int = 365) -> float | None:
    """Annualized realized volatility from daily returns (calendar-day basis)."""
    if len(data) < period + 1:
        return None
    returns = [(data[i] - data[i - 1]) / data[i - 1]
               for i in range(len(data) - period, len(data))
               if data[i - 1] != 0]
    if len(returns) < period:
        return None
    mean = sum(returns) / len(returns)
    variance = sum((r - mean) ** 2 for r in returns) / len(returns)
    return (variance ** 0.5) * (annualize ** 0.5)
