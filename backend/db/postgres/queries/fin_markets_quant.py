"""Quant market-data SQL templates for the ``fin_markets`` schema.

Covers ``fin_markets.quant_raw`` (API cache), ``fin_markets.quant_stats``
(OHLCV + technicals for equity/crypto/commodity/precious_metal/index), and
``fin_markets.quant_derivative_stats`` (options and futures contracts).

All constants are raw SQL strings ready for use with psycopg3 ``%s`` /
``%(name)s`` parameterisation.
"""

from __future__ import annotations

import logging

from backend.db.postgres.connection import raw_conn
from backend.db.postgres.errors import PG_QUERY_FAILED

logger = logging.getLogger(__name__)

__all__ = [
    "QuantRawSQL",
    "OhlcvStatsSQL",
    "CryptoStatsSQL",
    "CommodityStatsSQL",
    "PreciousMetalStatsSQL",
    "IndexStatsSQL",
    "OptionsStatsSQL",
    "DerivativeStatsSQL",
    "get_yf_exchange_for_symbol",
]

_GET_YF_EXCHANGE_SQL = """
    SELECT output->'stats_record'->>'yf_exchange' AS yf_exchange
    FROM fin_markets.quant_raw
    WHERE symbol = %s
      AND source = 'yfinance'
    ORDER BY created_at DESC
    LIMIT 1
"""


async def get_yf_exchange_for_symbol(symbol: str) -> str | None:
    """Return the yfinance exchange code for *symbol* from the most recent quant_raw entry.

    The ``yf_exchange`` field is written to ``quant_raw.output`` when OHLCV data
    is fetched via yfinance (e.g. during :func:`get_and_calculate_stats`).

    Args:
        symbol: Equity ticker symbol, e.g. ``'AAPL'``.

    Returns:
        yfinance exchange code string (e.g. ``'NMS'``, ``'NYQ'``, ``'HKG'``),
        or ``None`` when no yfinance entry exists yet or on DB error.
    """
    try:
        async with raw_conn(readonly=True) as conn:
            cur = await conn.execute(_GET_YF_EXCHANGE_SQL, (symbol.upper(),))
            row = await cur.fetchone()
        return row["yf_exchange"] if row and row["yf_exchange"] else None
    except Exception as exc:
        logger.error(
            "[%s] get_yf_exchange_for_symbol failed symbol=%r: %s", PG_QUERY_FAILED, symbol, exc
        )
        return None


class QuantRawSQL:
    """Queries against ``fin_markets.quant_raw`` (market-data API cache)."""

    GET_CACHED = """
        SELECT output, created_at
        FROM fin_markets.quant_raw
        WHERE cache_key = %s
          AND created_at > %s
        ORDER BY created_at DESC
        LIMIT 1
    """

    INSERT = """
        INSERT INTO fin_markets.quant_raw
            (thread_id, node_name, source, method, symbol, cache_key, input, output)
        VALUES (%s, %s, %s, %s, %s, %s, %s::jsonb, %s::jsonb)
    """

    LIST_BY_SYMBOL = """
        SELECT id, source, method, symbol, created_at
        FROM fin_markets.quant_raw
        WHERE symbol = %s
        ORDER BY created_at DESC
        LIMIT %s
    """

    PURGE_EXPIRED = """
        DELETE FROM fin_markets.quant_raw
        WHERE created_at < DATE_TRUNC('day', NOW() AT TIME ZONE 'UTC')
    """


class OhlcvStatsSQL:
    """Queries against ``fin_markets.quant_stats`` for equity (instrument_type='equity')."""

    UPSERT = """
        INSERT INTO fin_markets.quant_stats (
            symbol, instrument_type, currency_code, source, granularity, bar_time,
            open, high, low, close, volume, trade_count,
            sma_20, sma_50, sma_200, ema_12, ema_26,
            macd_line, macd_signal, macd_hist,
            rsi_14, stoch_k, stoch_d,
            atr_14, bb_upper, bb_middle, bb_lower,
            adx_14, plus_di_14, minus_di_14,
            aroon_up_14, aroon_down_14, sar,
            willr_14, cci_20, mfi_14, roc_10, natr_14,
            vwap, obv, ad,
            index_code
        ) VALUES (
            %(symbol)s, 'equity', %(currency_code)s, %(source)s, %(granularity)s, %(bar_time)s,
            %(open)s, %(high)s, %(low)s, %(close)s, %(volume)s, %(trade_count)s,
            %(sma_20)s, %(sma_50)s, %(sma_200)s, %(ema_12)s, %(ema_26)s,
            %(macd_line)s, %(macd_signal)s, %(macd_hist)s,
            %(rsi_14)s, %(stoch_k)s, %(stoch_d)s,
            %(atr_14)s, %(bb_upper)s, %(bb_middle)s, %(bb_lower)s,
            %(adx_14)s, %(plus_di_14)s, %(minus_di_14)s,
            %(aroon_up_14)s, %(aroon_down_14)s, %(sar)s,
            %(willr_14)s, %(cci_20)s, %(mfi_14)s, %(roc_10)s, %(natr_14)s,
            %(vwap)s, %(obv)s, %(ad)s,
            %(index_code)s
        )
        ON CONFLICT (instrument_type, symbol, source, granularity, bar_time)
        DO UPDATE SET
            open          = EXCLUDED.open,
            high          = EXCLUDED.high,
            low           = EXCLUDED.low,
            close         = EXCLUDED.close,
            volume        = EXCLUDED.volume,
            trade_count   = COALESCE(EXCLUDED.trade_count, fin_markets.quant_stats.trade_count),
            sma_20        = COALESCE(EXCLUDED.sma_20,      fin_markets.quant_stats.sma_20),
            sma_50        = COALESCE(EXCLUDED.sma_50,      fin_markets.quant_stats.sma_50),
            sma_200       = COALESCE(EXCLUDED.sma_200,     fin_markets.quant_stats.sma_200),
            ema_12        = COALESCE(EXCLUDED.ema_12,      fin_markets.quant_stats.ema_12),
            ema_26        = COALESCE(EXCLUDED.ema_26,      fin_markets.quant_stats.ema_26),
            macd_line     = COALESCE(EXCLUDED.macd_line,   fin_markets.quant_stats.macd_line),
            macd_signal   = COALESCE(EXCLUDED.macd_signal, fin_markets.quant_stats.macd_signal),
            macd_hist     = COALESCE(EXCLUDED.macd_hist,   fin_markets.quant_stats.macd_hist),
            rsi_14        = COALESCE(EXCLUDED.rsi_14,      fin_markets.quant_stats.rsi_14),
            stoch_k       = COALESCE(EXCLUDED.stoch_k,     fin_markets.quant_stats.stoch_k),
            stoch_d       = COALESCE(EXCLUDED.stoch_d,     fin_markets.quant_stats.stoch_d),
            atr_14        = COALESCE(EXCLUDED.atr_14,      fin_markets.quant_stats.atr_14),
            bb_upper      = COALESCE(EXCLUDED.bb_upper,    fin_markets.quant_stats.bb_upper),
            bb_middle     = COALESCE(EXCLUDED.bb_middle,   fin_markets.quant_stats.bb_middle),
            bb_lower      = COALESCE(EXCLUDED.bb_lower,    fin_markets.quant_stats.bb_lower),
            adx_14        = COALESCE(EXCLUDED.adx_14,      fin_markets.quant_stats.adx_14),
            plus_di_14    = COALESCE(EXCLUDED.plus_di_14,  fin_markets.quant_stats.plus_di_14),
            minus_di_14   = COALESCE(EXCLUDED.minus_di_14, fin_markets.quant_stats.minus_di_14),
            aroon_up_14   = COALESCE(EXCLUDED.aroon_up_14,   fin_markets.quant_stats.aroon_up_14),
            aroon_down_14 = COALESCE(EXCLUDED.aroon_down_14, fin_markets.quant_stats.aroon_down_14),
            sar           = COALESCE(EXCLUDED.sar,         fin_markets.quant_stats.sar),
            willr_14      = COALESCE(EXCLUDED.willr_14,    fin_markets.quant_stats.willr_14),
            cci_20        = COALESCE(EXCLUDED.cci_20,      fin_markets.quant_stats.cci_20),
            mfi_14        = COALESCE(EXCLUDED.mfi_14,      fin_markets.quant_stats.mfi_14),
            roc_10        = COALESCE(EXCLUDED.roc_10,      fin_markets.quant_stats.roc_10),
            natr_14       = COALESCE(EXCLUDED.natr_14,     fin_markets.quant_stats.natr_14),
            vwap          = COALESCE(EXCLUDED.vwap,        fin_markets.quant_stats.vwap),
            obv           = COALESCE(EXCLUDED.obv,         fin_markets.quant_stats.obv),
            ad            = COALESCE(EXCLUDED.ad,          fin_markets.quant_stats.ad),
            index_code    = COALESCE(EXCLUDED.index_code,  fin_markets.quant_stats.index_code)
    """

    GET_COVERAGE = """
        SELECT MAX(bar_time) AS latest
        FROM fin_markets.quant_stats
        WHERE symbol = %s
          AND instrument_type = 'equity'
          AND granularity = %s
          AND bar_time >= %s
    """

    GET_BARS_IN_WINDOW = """
        SELECT bar_time, open, high, low, close, volume
        FROM fin_markets.quant_stats
        WHERE symbol = %s
          AND instrument_type = 'equity'
          AND granularity = %s
          AND bar_time >= %s
        ORDER BY bar_time ASC
    """

    GET_SMA_EMA_BARS_IN_WINDOW = """
        SELECT bar_time, sma_20, sma_50, ema_12, ema_26
        FROM fin_markets.quant_stats
        WHERE symbol = %s
          AND instrument_type = 'equity'
          AND granularity = %s
          AND bar_time >= %s
        ORDER BY bar_time ASC
    """

    COUNT_BY_SYMBOL_GRANULARITY = """
        SELECT COUNT(*) AS row_count
        FROM fin_markets.quant_stats
        WHERE symbol = %s
          AND instrument_type = 'equity'
          AND granularity = %s
    """

    GET_BY_SYMBOL = """
        SELECT *
        FROM fin_markets.quant_stats
        WHERE symbol = %(symbol)s
          AND instrument_type = 'equity'
          AND granularity = %(granularity)s
        ORDER BY bar_time DESC
        LIMIT %(limit)s
    """

    GET_LATEST_ID = """
        SELECT id
        FROM fin_markets.quant_stats
        WHERE symbol = %s
          AND instrument_type = 'equity'
          AND granularity = %s
        ORDER BY bar_time DESC
        LIMIT 1
    """

    @staticmethod
    def get_indicator_series(columns: list[str]) -> str:
        """Build a parameterised SELECT for the given whitelisted indicator columns.

        Column names must be pre-validated against the allowed whitelist by the
        caller before passing here — this method does no sanitisation itself.

        Args:
            columns: List of validated ``quant_stats`` column names to fetch,
                     e.g. ``['sma_20']`` or ``['bb_upper', 'bb_middle', 'bb_lower']``.

        Returns:
            SQL string selecting ``bar_time`` plus the requested columns, ordered
            ascending by ``bar_time``.
        """
        col_select = ", ".join(columns)
        return f"""
            SELECT bar_time, {col_select}
            FROM fin_markets.quant_stats
            WHERE symbol = %(symbol)s
              AND instrument_type = %(instrument_type)s
              AND granularity = %(granularity)s
            ORDER BY bar_time ASC
        """


class IndexStatsSQL:
    """Queries against ``fin_markets.quant_stats`` for indices (instrument_type='index')."""

    UPSERT = """
        INSERT INTO fin_markets.quant_stats (
            symbol, instrument_type, currency_code, source, granularity, bar_time,
            open, high, low, close, volume,
            sma_20, sma_50, sma_200, ema_12, ema_26,
            macd_line, macd_signal, macd_hist,
            rsi_14, stoch_k, stoch_d, willr_14, cci_20, roc_10,
            atr_14, bb_upper, bb_middle, bb_lower, natr_14,
            adx_14, plus_di_14, minus_di_14, aroon_up_14, aroon_down_14, sar,
            obv, index_code
        ) VALUES (
            %(symbol)s, 'index', %(currency_code)s, %(source)s, %(granularity)s, %(bar_time)s,
            %(open)s, %(high)s, %(low)s, %(close)s, %(volume)s,
            %(sma_20)s, %(sma_50)s, %(sma_200)s, %(ema_12)s, %(ema_26)s,
            %(macd_line)s, %(macd_signal)s, %(macd_hist)s,
            %(rsi_14)s, %(stoch_k)s, %(stoch_d)s, %(willr_14)s, %(cci_20)s, %(roc_10)s,
            %(atr_14)s, %(bb_upper)s, %(bb_middle)s, %(bb_lower)s, %(natr_14)s,
            %(adx_14)s, %(plus_di_14)s, %(minus_di_14)s, %(aroon_up_14)s, %(aroon_down_14)s, %(sar)s,
            %(obv)s, %(index_code)s
        )
        ON CONFLICT (instrument_type, symbol, source, granularity, bar_time)
        DO UPDATE SET
            open        = EXCLUDED.open,
            high        = EXCLUDED.high,
            low         = EXCLUDED.low,
            close       = EXCLUDED.close,
            volume      = EXCLUDED.volume,
            sma_20      = COALESCE(EXCLUDED.sma_20,      fin_markets.quant_stats.sma_20),
            sma_50      = COALESCE(EXCLUDED.sma_50,      fin_markets.quant_stats.sma_50),
            sma_200     = COALESCE(EXCLUDED.sma_200,     fin_markets.quant_stats.sma_200),
            ema_12      = COALESCE(EXCLUDED.ema_12,      fin_markets.quant_stats.ema_12),
            ema_26      = COALESCE(EXCLUDED.ema_26,      fin_markets.quant_stats.ema_26),
            macd_line   = COALESCE(EXCLUDED.macd_line,   fin_markets.quant_stats.macd_line),
            macd_signal = COALESCE(EXCLUDED.macd_signal, fin_markets.quant_stats.macd_signal),
            macd_hist   = COALESCE(EXCLUDED.macd_hist,   fin_markets.quant_stats.macd_hist),
            rsi_14      = COALESCE(EXCLUDED.rsi_14,      fin_markets.quant_stats.rsi_14),
            stoch_k     = COALESCE(EXCLUDED.stoch_k,     fin_markets.quant_stats.stoch_k),
            stoch_d     = COALESCE(EXCLUDED.stoch_d,     fin_markets.quant_stats.stoch_d),
            willr_14    = COALESCE(EXCLUDED.willr_14,    fin_markets.quant_stats.willr_14),
            cci_20      = COALESCE(EXCLUDED.cci_20,      fin_markets.quant_stats.cci_20),
            roc_10      = COALESCE(EXCLUDED.roc_10,      fin_markets.quant_stats.roc_10),
            atr_14      = COALESCE(EXCLUDED.atr_14,      fin_markets.quant_stats.atr_14),
            bb_upper    = COALESCE(EXCLUDED.bb_upper,    fin_markets.quant_stats.bb_upper),
            bb_middle   = COALESCE(EXCLUDED.bb_middle,   fin_markets.quant_stats.bb_middle),
            bb_lower    = COALESCE(EXCLUDED.bb_lower,    fin_markets.quant_stats.bb_lower),
            natr_14     = COALESCE(EXCLUDED.natr_14,     fin_markets.quant_stats.natr_14),
            adx_14      = COALESCE(EXCLUDED.adx_14,      fin_markets.quant_stats.adx_14),
            plus_di_14  = COALESCE(EXCLUDED.plus_di_14,  fin_markets.quant_stats.plus_di_14),
            minus_di_14 = COALESCE(EXCLUDED.minus_di_14, fin_markets.quant_stats.minus_di_14),
            aroon_up_14 = COALESCE(EXCLUDED.aroon_up_14, fin_markets.quant_stats.aroon_up_14),
            aroon_down_14 = COALESCE(EXCLUDED.aroon_down_14, fin_markets.quant_stats.aroon_down_14),
            sar         = COALESCE(EXCLUDED.sar,         fin_markets.quant_stats.sar),
            obv           = COALESCE(EXCLUDED.obv,           fin_markets.quant_stats.obv),
            currency_code = COALESCE(EXCLUDED.currency_code, fin_markets.quant_stats.currency_code),
            index_code    = COALESCE(EXCLUDED.index_code,    fin_markets.quant_stats.index_code)
    """

    GET_COVERAGE = """
        SELECT MAX(bar_time) AS latest
        FROM fin_markets.quant_stats
        WHERE symbol = %s
          AND instrument_type = 'index'
          AND granularity = %s
          AND bar_time >= %s
    """

    COUNT_BY_SYMBOL_GRANULARITY = """
        SELECT COUNT(*) AS row_count
        FROM fin_markets.quant_stats
        WHERE symbol = %s
          AND instrument_type = 'index'
          AND granularity = %s
    """

    GET_RECENT = """
        SELECT bar_time, open, high, low, close, volume, rsi_14, macd_line, macd_signal
        FROM fin_markets.quant_stats
        WHERE symbol = %(symbol)s
          AND instrument_type = 'index'
          AND granularity  = %(granularity)s
        ORDER BY bar_time DESC
        LIMIT %(limit)s
    """


class CryptoStatsSQL:
    """Queries against ``fin_markets.quant_stats`` for crypto (instrument_type='crypto').

    Used for cryptocurrency spot pairs (e.g. ``'BTC-USD'``, ``'ETH-USD'``).
    Column set is identical to :class:`OhlcvStatsSQL` — full OHLCV + all technicals.
    """

    UPSERT = """
        INSERT INTO fin_markets.quant_stats (
            symbol, instrument_type, currency_code, source, granularity, bar_time,
            open, high, low, close, volume, trade_count,
            sma_20, sma_50, sma_200, ema_12, ema_26,
            macd_line, macd_signal, macd_hist,
            rsi_14, stoch_k, stoch_d,
            atr_14, bb_upper, bb_middle, bb_lower,
            adx_14, plus_di_14, minus_di_14,
            aroon_up_14, aroon_down_14, sar,
            willr_14, cci_20, mfi_14, roc_10, natr_14,
            vwap, obv, ad,
            index_code
        ) VALUES (
            %(symbol)s, 'crypto', %(currency_code)s, %(source)s, %(granularity)s, %(bar_time)s,
            %(open)s, %(high)s, %(low)s, %(close)s, %(volume)s, %(trade_count)s,
            %(sma_20)s, %(sma_50)s, %(sma_200)s, %(ema_12)s, %(ema_26)s,
            %(macd_line)s, %(macd_signal)s, %(macd_hist)s,
            %(rsi_14)s, %(stoch_k)s, %(stoch_d)s,
            %(atr_14)s, %(bb_upper)s, %(bb_middle)s, %(bb_lower)s,
            %(adx_14)s, %(plus_di_14)s, %(minus_di_14)s,
            %(aroon_up_14)s, %(aroon_down_14)s, %(sar)s,
            %(willr_14)s, %(cci_20)s, %(mfi_14)s, %(roc_10)s, %(natr_14)s,
            %(vwap)s, %(obv)s, %(ad)s,
            %(index_code)s
        )
        ON CONFLICT (instrument_type, symbol, source, granularity, bar_time)
        DO UPDATE SET
            open          = EXCLUDED.open,
            high          = EXCLUDED.high,
            low           = EXCLUDED.low,
            close         = EXCLUDED.close,
            volume        = EXCLUDED.volume,
            trade_count   = COALESCE(EXCLUDED.trade_count, fin_markets.quant_stats.trade_count),
            sma_20        = COALESCE(EXCLUDED.sma_20,      fin_markets.quant_stats.sma_20),
            sma_50        = COALESCE(EXCLUDED.sma_50,      fin_markets.quant_stats.sma_50),
            sma_200       = COALESCE(EXCLUDED.sma_200,     fin_markets.quant_stats.sma_200),
            ema_12        = COALESCE(EXCLUDED.ema_12,      fin_markets.quant_stats.ema_12),
            ema_26        = COALESCE(EXCLUDED.ema_26,      fin_markets.quant_stats.ema_26),
            macd_line     = COALESCE(EXCLUDED.macd_line,   fin_markets.quant_stats.macd_line),
            macd_signal   = COALESCE(EXCLUDED.macd_signal, fin_markets.quant_stats.macd_signal),
            macd_hist     = COALESCE(EXCLUDED.macd_hist,   fin_markets.quant_stats.macd_hist),
            rsi_14        = COALESCE(EXCLUDED.rsi_14,      fin_markets.quant_stats.rsi_14),
            stoch_k       = COALESCE(EXCLUDED.stoch_k,     fin_markets.quant_stats.stoch_k),
            stoch_d       = COALESCE(EXCLUDED.stoch_d,     fin_markets.quant_stats.stoch_d),
            atr_14        = COALESCE(EXCLUDED.atr_14,      fin_markets.quant_stats.atr_14),
            bb_upper      = COALESCE(EXCLUDED.bb_upper,    fin_markets.quant_stats.bb_upper),
            bb_middle     = COALESCE(EXCLUDED.bb_middle,   fin_markets.quant_stats.bb_middle),
            bb_lower      = COALESCE(EXCLUDED.bb_lower,    fin_markets.quant_stats.bb_lower),
            adx_14        = COALESCE(EXCLUDED.adx_14,      fin_markets.quant_stats.adx_14),
            plus_di_14    = COALESCE(EXCLUDED.plus_di_14,  fin_markets.quant_stats.plus_di_14),
            minus_di_14   = COALESCE(EXCLUDED.minus_di_14, fin_markets.quant_stats.minus_di_14),
            aroon_up_14   = COALESCE(EXCLUDED.aroon_up_14,   fin_markets.quant_stats.aroon_up_14),
            aroon_down_14 = COALESCE(EXCLUDED.aroon_down_14, fin_markets.quant_stats.aroon_down_14),
            sar           = COALESCE(EXCLUDED.sar,         fin_markets.quant_stats.sar),
            willr_14      = COALESCE(EXCLUDED.willr_14,    fin_markets.quant_stats.willr_14),
            cci_20        = COALESCE(EXCLUDED.cci_20,      fin_markets.quant_stats.cci_20),
            mfi_14        = COALESCE(EXCLUDED.mfi_14,      fin_markets.quant_stats.mfi_14),
            roc_10        = COALESCE(EXCLUDED.roc_10,      fin_markets.quant_stats.roc_10),
            natr_14       = COALESCE(EXCLUDED.natr_14,     fin_markets.quant_stats.natr_14),
            vwap          = COALESCE(EXCLUDED.vwap,        fin_markets.quant_stats.vwap),
            obv           = COALESCE(EXCLUDED.obv,         fin_markets.quant_stats.obv),
            ad            = COALESCE(EXCLUDED.ad,          fin_markets.quant_stats.ad),
            index_code    = COALESCE(EXCLUDED.index_code,  fin_markets.quant_stats.index_code)
    """

    COUNT_BY_SYMBOL_GRANULARITY = """
        SELECT COUNT(*) AS row_count
        FROM fin_markets.quant_stats
        WHERE symbol = %s
          AND instrument_type = 'crypto'
          AND granularity = %s
    """


class CommodityStatsSQL:
    """Queries against ``fin_markets.quant_stats`` for commodity futures (instrument_type='commodity').

    Used for commodity futures tickers (e.g. ``'GC=F'``, ``'CL=F'``, ``'NG=F'``, ``'SI=F'``).
    Column set is identical to :class:`OhlcvStatsSQL` — full OHLCV + all technicals.
    """

    UPSERT = """
        INSERT INTO fin_markets.quant_stats (
            symbol, instrument_type, currency_code, source, granularity, bar_time,
            open, high, low, close, volume, trade_count,
            sma_20, sma_50, sma_200, ema_12, ema_26,
            macd_line, macd_signal, macd_hist,
            rsi_14, stoch_k, stoch_d,
            atr_14, bb_upper, bb_middle, bb_lower,
            adx_14, plus_di_14, minus_di_14,
            aroon_up_14, aroon_down_14, sar,
            willr_14, cci_20, mfi_14, roc_10, natr_14,
            vwap, obv, ad,
            index_code
        ) VALUES (
            %(symbol)s, 'commodity', %(currency_code)s, %(source)s, %(granularity)s, %(bar_time)s,
            %(open)s, %(high)s, %(low)s, %(close)s, %(volume)s, %(trade_count)s,
            %(sma_20)s, %(sma_50)s, %(sma_200)s, %(ema_12)s, %(ema_26)s,
            %(macd_line)s, %(macd_signal)s, %(macd_hist)s,
            %(rsi_14)s, %(stoch_k)s, %(stoch_d)s,
            %(atr_14)s, %(bb_upper)s, %(bb_middle)s, %(bb_lower)s,
            %(adx_14)s, %(plus_di_14)s, %(minus_di_14)s,
            %(aroon_up_14)s, %(aroon_down_14)s, %(sar)s,
            %(willr_14)s, %(cci_20)s, %(mfi_14)s, %(roc_10)s, %(natr_14)s,
            %(vwap)s, %(obv)s, %(ad)s,
            %(index_code)s
        )
        ON CONFLICT (instrument_type, symbol, source, granularity, bar_time)
        DO UPDATE SET
            open          = EXCLUDED.open,
            high          = EXCLUDED.high,
            low           = EXCLUDED.low,
            close         = EXCLUDED.close,
            volume        = EXCLUDED.volume,
            trade_count   = COALESCE(EXCLUDED.trade_count, fin_markets.quant_stats.trade_count),
            sma_20        = COALESCE(EXCLUDED.sma_20,      fin_markets.quant_stats.sma_20),
            sma_50        = COALESCE(EXCLUDED.sma_50,      fin_markets.quant_stats.sma_50),
            sma_200       = COALESCE(EXCLUDED.sma_200,     fin_markets.quant_stats.sma_200),
            ema_12        = COALESCE(EXCLUDED.ema_12,      fin_markets.quant_stats.ema_12),
            ema_26        = COALESCE(EXCLUDED.ema_26,      fin_markets.quant_stats.ema_26),
            macd_line     = COALESCE(EXCLUDED.macd_line,   fin_markets.quant_stats.macd_line),
            macd_signal   = COALESCE(EXCLUDED.macd_signal, fin_markets.quant_stats.macd_signal),
            macd_hist     = COALESCE(EXCLUDED.macd_hist,   fin_markets.quant_stats.macd_hist),
            rsi_14        = COALESCE(EXCLUDED.rsi_14,      fin_markets.quant_stats.rsi_14),
            stoch_k       = COALESCE(EXCLUDED.stoch_k,     fin_markets.quant_stats.stoch_k),
            stoch_d       = COALESCE(EXCLUDED.stoch_d,     fin_markets.quant_stats.stoch_d),
            atr_14        = COALESCE(EXCLUDED.atr_14,      fin_markets.quant_stats.atr_14),
            bb_upper      = COALESCE(EXCLUDED.bb_upper,    fin_markets.quant_stats.bb_upper),
            bb_middle     = COALESCE(EXCLUDED.bb_middle,   fin_markets.quant_stats.bb_middle),
            bb_lower      = COALESCE(EXCLUDED.bb_lower,    fin_markets.quant_stats.bb_lower),
            adx_14        = COALESCE(EXCLUDED.adx_14,      fin_markets.quant_stats.adx_14),
            plus_di_14    = COALESCE(EXCLUDED.plus_di_14,  fin_markets.quant_stats.plus_di_14),
            minus_di_14   = COALESCE(EXCLUDED.minus_di_14, fin_markets.quant_stats.minus_di_14),
            aroon_up_14   = COALESCE(EXCLUDED.aroon_up_14,   fin_markets.quant_stats.aroon_up_14),
            aroon_down_14 = COALESCE(EXCLUDED.aroon_down_14, fin_markets.quant_stats.aroon_down_14),
            sar           = COALESCE(EXCLUDED.sar,         fin_markets.quant_stats.sar),
            willr_14      = COALESCE(EXCLUDED.willr_14,    fin_markets.quant_stats.willr_14),
            cci_20        = COALESCE(EXCLUDED.cci_20,      fin_markets.quant_stats.cci_20),
            mfi_14        = COALESCE(EXCLUDED.mfi_14,      fin_markets.quant_stats.mfi_14),
            roc_10        = COALESCE(EXCLUDED.roc_10,      fin_markets.quant_stats.roc_10),
            natr_14       = COALESCE(EXCLUDED.natr_14,     fin_markets.quant_stats.natr_14),
            vwap          = COALESCE(EXCLUDED.vwap,        fin_markets.quant_stats.vwap),
            obv           = COALESCE(EXCLUDED.obv,         fin_markets.quant_stats.obv),
            ad            = COALESCE(EXCLUDED.ad,          fin_markets.quant_stats.ad),
            index_code    = COALESCE(EXCLUDED.index_code,  fin_markets.quant_stats.index_code)
    """

    COUNT_BY_SYMBOL_GRANULARITY = """
        SELECT COUNT(*) AS row_count
        FROM fin_markets.quant_stats
        WHERE symbol = %s
          AND instrument_type = 'commodity'
          AND granularity = %s
    """


class PreciousMetalStatsSQL:
    """Queries against ``fin_markets.quant_stats`` for precious metals (instrument_type='precious_metal').

    Used for precious metal futures tickers (e.g. ``'GC=F'`` gold, ``'SI=F'`` silver).
    Column set is identical to :class:`OhlcvStatsSQL` — full OHLCV + all technicals.
    """

    UPSERT = """
        INSERT INTO fin_markets.quant_stats (
            symbol, instrument_type, currency_code, source, granularity, bar_time,
            open, high, low, close, volume, trade_count,
            sma_20, sma_50, sma_200, ema_12, ema_26,
            macd_line, macd_signal, macd_hist,
            rsi_14, stoch_k, stoch_d,
            atr_14, bb_upper, bb_middle, bb_lower,
            adx_14, plus_di_14, minus_di_14,
            aroon_up_14, aroon_down_14, sar,
            willr_14, cci_20, mfi_14, roc_10, natr_14,
            vwap, obv, ad,
            index_code
        ) VALUES (
            %(symbol)s, 'precious_metal', %(currency_code)s, %(source)s, %(granularity)s, %(bar_time)s,
            %(open)s, %(high)s, %(low)s, %(close)s, %(volume)s, %(trade_count)s,
            %(sma_20)s, %(sma_50)s, %(sma_200)s, %(ema_12)s, %(ema_26)s,
            %(macd_line)s, %(macd_signal)s, %(macd_hist)s,
            %(rsi_14)s, %(stoch_k)s, %(stoch_d)s,
            %(atr_14)s, %(bb_upper)s, %(bb_middle)s, %(bb_lower)s,
            %(adx_14)s, %(plus_di_14)s, %(minus_di_14)s,
            %(aroon_up_14)s, %(aroon_down_14)s, %(sar)s,
            %(willr_14)s, %(cci_20)s, %(mfi_14)s, %(roc_10)s, %(natr_14)s,
            %(vwap)s, %(obv)s, %(ad)s,
            %(index_code)s
        )
        ON CONFLICT (instrument_type, symbol, source, granularity, bar_time)
        DO UPDATE SET
            open          = EXCLUDED.open,
            high          = EXCLUDED.high,
            low           = EXCLUDED.low,
            close         = EXCLUDED.close,
            volume        = EXCLUDED.volume,
            trade_count   = COALESCE(EXCLUDED.trade_count, fin_markets.quant_stats.trade_count),
            sma_20        = COALESCE(EXCLUDED.sma_20,      fin_markets.quant_stats.sma_20),
            sma_50        = COALESCE(EXCLUDED.sma_50,      fin_markets.quant_stats.sma_50),
            sma_200       = COALESCE(EXCLUDED.sma_200,     fin_markets.quant_stats.sma_200),
            ema_12        = COALESCE(EXCLUDED.ema_12,      fin_markets.quant_stats.ema_12),
            ema_26        = COALESCE(EXCLUDED.ema_26,      fin_markets.quant_stats.ema_26),
            macd_line     = COALESCE(EXCLUDED.macd_line,   fin_markets.quant_stats.macd_line),
            macd_signal   = COALESCE(EXCLUDED.macd_signal, fin_markets.quant_stats.macd_signal),
            macd_hist     = COALESCE(EXCLUDED.macd_hist,   fin_markets.quant_stats.macd_hist),
            rsi_14        = COALESCE(EXCLUDED.rsi_14,      fin_markets.quant_stats.rsi_14),
            stoch_k       = COALESCE(EXCLUDED.stoch_k,     fin_markets.quant_stats.stoch_k),
            stoch_d       = COALESCE(EXCLUDED.stoch_d,     fin_markets.quant_stats.stoch_d),
            atr_14        = COALESCE(EXCLUDED.atr_14,      fin_markets.quant_stats.atr_14),
            bb_upper      = COALESCE(EXCLUDED.bb_upper,    fin_markets.quant_stats.bb_upper),
            bb_middle     = COALESCE(EXCLUDED.bb_middle,   fin_markets.quant_stats.bb_middle),
            bb_lower      = COALESCE(EXCLUDED.bb_lower,    fin_markets.quant_stats.bb_lower),
            adx_14        = COALESCE(EXCLUDED.adx_14,      fin_markets.quant_stats.adx_14),
            plus_di_14    = COALESCE(EXCLUDED.plus_di_14,  fin_markets.quant_stats.plus_di_14),
            minus_di_14   = COALESCE(EXCLUDED.minus_di_14, fin_markets.quant_stats.minus_di_14),
            aroon_up_14   = COALESCE(EXCLUDED.aroon_up_14,   fin_markets.quant_stats.aroon_up_14),
            aroon_down_14 = COALESCE(EXCLUDED.aroon_down_14, fin_markets.quant_stats.aroon_down_14),
            sar           = COALESCE(EXCLUDED.sar,         fin_markets.quant_stats.sar),
            willr_14      = COALESCE(EXCLUDED.willr_14,    fin_markets.quant_stats.willr_14),
            cci_20        = COALESCE(EXCLUDED.cci_20,      fin_markets.quant_stats.cci_20),
            mfi_14        = COALESCE(EXCLUDED.mfi_14,      fin_markets.quant_stats.mfi_14),
            roc_10        = COALESCE(EXCLUDED.roc_10,      fin_markets.quant_stats.roc_10),
            natr_14       = COALESCE(EXCLUDED.natr_14,     fin_markets.quant_stats.natr_14),
            vwap          = COALESCE(EXCLUDED.vwap,        fin_markets.quant_stats.vwap),
            obv           = COALESCE(EXCLUDED.obv,         fin_markets.quant_stats.obv),
            ad            = COALESCE(EXCLUDED.ad,          fin_markets.quant_stats.ad),
            index_code    = COALESCE(EXCLUDED.index_code,  fin_markets.quant_stats.index_code)
    """

    COUNT_BY_SYMBOL_GRANULARITY = """
        SELECT COUNT(*) AS row_count
        FROM fin_markets.quant_stats
        WHERE symbol = %s
          AND instrument_type = 'precious_metal'
          AND granularity = %s
    """


class OptionsStatsSQL:
    """Queries against ``fin_markets.quant_options_stats`` (per-contract options rows).

    ``UPSERT`` writes one row per individual call/put contract.  The unique key is
    ``(symbol, source, contract_name)``; re-ingesting the same contract refreshes its
    latest snapshot.  ``options_type``, ``expiry_date`` and ``strike`` are parsed from
    the OSI ``contract_name`` and always overwritten; quote fields are preserved with
    ``COALESCE`` when a newer snapshot omits them.
    """

    UPSERT = """
        INSERT INTO fin_markets.quant_options_stats (
            symbol, source, contract_name, options_type, expiry_date, strike,
            last_trade_date, last_price, bid, ask,
            price_change, pct_change, volume, open_interest, implied_volatility
        ) VALUES (
            %(symbol)s, %(source)s, %(contract_name)s, %(options_type)s, %(expiry_date)s, %(strike)s,
            %(last_trade_date)s, %(last_price)s, %(bid)s, %(ask)s,
            %(price_change)s, %(pct_change)s, %(volume)s, %(open_interest)s, %(implied_volatility)s
        )
        ON CONFLICT (symbol, source, contract_name) DO UPDATE SET
            options_type       = EXCLUDED.options_type,
            expiry_date        = EXCLUDED.expiry_date,
            strike             = EXCLUDED.strike,
            last_trade_date    = COALESCE(EXCLUDED.last_trade_date,    fin_markets.quant_options_stats.last_trade_date),
            last_price         = COALESCE(EXCLUDED.last_price,         fin_markets.quant_options_stats.last_price),
            bid                = COALESCE(EXCLUDED.bid,                fin_markets.quant_options_stats.bid),
            ask                = COALESCE(EXCLUDED.ask,                fin_markets.quant_options_stats.ask),
            price_change       = COALESCE(EXCLUDED.price_change,       fin_markets.quant_options_stats.price_change),
            pct_change         = COALESCE(EXCLUDED.pct_change,         fin_markets.quant_options_stats.pct_change),
            volume             = COALESCE(EXCLUDED.volume,             fin_markets.quant_options_stats.volume),
            open_interest      = COALESCE(EXCLUDED.open_interest,      fin_markets.quant_options_stats.open_interest),
            implied_volatility = COALESCE(EXCLUDED.implied_volatility, fin_markets.quant_options_stats.implied_volatility),
            created_at         = NOW()
        RETURNING id
    """


class DerivativeStatsSQL:
    """Queries against ``fin_markets.quant_derivative_stats`` (aggregate per-expiry rows).

    ``UPSERT_OPTIONS_AGGREGATE`` writes one row per (symbol, source, expiry_date) for
    options, with ``contract_name = NULL``, carrying the ``estimated_price`` where the
    call breakeven (strike + call cost) and put breakeven (strike - put cost) meet at the
    ATM ``cross_strike``.  The unique key is
    ``(derivative_type, symbol, source, expiry_date, COALESCE(contract_name, ''))``.
    """

    UPSERT_OPTIONS_AGGREGATE = """
        INSERT INTO fin_markets.quant_derivative_stats (
            symbol, derivative_type, source, contract_name, expiry_date,
            estimated_price, cross_strike
        ) VALUES (
            %(symbol)s, 'options', %(source)s, NULL, %(expiry_date)s,
            %(estimated_price)s, %(cross_strike)s
        )
        ON CONFLICT (
            derivative_type, symbol, source, expiry_date,
            COALESCE(contract_name, '')
        ) DO UPDATE SET
            estimated_price = EXCLUDED.estimated_price,
            cross_strike    = EXCLUDED.cross_strike,
            created_at      = NOW()
        RETURNING id
    """
