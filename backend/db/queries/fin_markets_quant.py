"""Quant market-data SQL templates for the ``fin_markets`` schema.

Covers ``fin_markets.quant_raw`` (API cache) and ``fin_markets.quant_stats``
for equities, futures, options, and indices.

All constants are raw SQL strings ready for use with psycopg3 ``%s`` /
``%(name)s`` parameterisation.
"""

from __future__ import annotations


class QuantRawSQL:
    """Queries against ``fin_markets.quant_raw`` (market-data API cache)."""

    GET_CACHED = """
        SELECT output
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
        WHERE created_at < NOW() - INTERVAL '4 hours'
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
            region
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
            %(region)s
        )
        ON CONFLICT (
            instrument_type, symbol, source, granularity, bar_time,
            COALESCE(contract_ticker, ''), COALESCE(expiry, ''), COALESCE(option_type, '')
        ) DO UPDATE SET
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
            region        = COALESCE(EXCLUDED.region,      fin_markets.quant_stats.region)
    """

    GET_COVERAGE = """
        SELECT MAX(bar_time) AS latest
        FROM fin_markets.quant_stats
        WHERE symbol = %s
          AND instrument_type = 'equity'
          AND granularity = %s
          AND bar_time >= %s
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


class FuturesStatsSQL:
    """Queries against ``fin_markets.quant_stats`` for futures (instrument_type='futures')."""

    GET_COVERAGE = """
        SELECT MAX(bar_time) AS latest
        FROM fin_markets.quant_stats
        WHERE symbol = %s
          AND instrument_type = 'futures'
          AND contract_ticker = %s
          AND bar_time >= %s
    """

    UPSERT = """
        INSERT INTO fin_markets.quant_stats (
            symbol, instrument_type, currency_code, contract_ticker, expiry, source, granularity, bar_time,
            open, high, low, close, volume, open_interest, region
        ) VALUES (
            %(symbol)s, 'futures', %(currency_code)s, %(contract_ticker)s, %(expiry)s, %(source)s, '1day', %(bar_time)s,
            %(open)s, %(high)s, %(low)s, %(close)s, %(volume)s, %(open_interest)s, %(region)s
        )
        ON CONFLICT (
            instrument_type, symbol, source, granularity, bar_time,
            COALESCE(contract_ticker, ''), COALESCE(expiry, ''), COALESCE(option_type, '')
        ) DO UPDATE SET
            open          = EXCLUDED.open,
            high          = EXCLUDED.high,
            low           = EXCLUDED.low,
            close         = EXCLUDED.close,
            volume        = COALESCE(EXCLUDED.volume,        fin_markets.quant_stats.volume),
            open_interest = COALESCE(EXCLUDED.open_interest, fin_markets.quant_stats.open_interest),
            currency_code = COALESCE(EXCLUDED.currency_code, fin_markets.quant_stats.currency_code),
            region        = COALESCE(EXCLUDED.region,        fin_markets.quant_stats.region)
    """

    GET_RECENT = """
        SELECT bar_time, open, high, low, close, volume, open_interest
        FROM fin_markets.quant_stats
        WHERE instrument_type = 'futures'
          AND contract_ticker = %(contract_ticker)s
        ORDER BY bar_time DESC
        LIMIT %(limit)s
    """


class OptionsStatsSQL:
    """Queries against ``fin_markets.quant_stats`` for options flow (instrument_type='options')."""

    GET_LATEST = """
        SELECT id, calls_oi, puts_oi, calls_puts_ratio, net_flow, query_used, bar_time
        FROM fin_markets.quant_stats
        WHERE symbol = %s
          AND instrument_type = 'options'
          AND expiry = %s
          AND bar_time > %s
        ORDER BY bar_time DESC
        LIMIT 1
    """

    UPSERT = """
        INSERT INTO fin_markets.quant_stats (
            symbol, instrument_type, currency_code, expiry, source, granularity, bar_time,
            calls_oi, puts_oi, calls_puts_ratio, net_flow, query_used, region
        ) VALUES (
            %(symbol)s, 'options', %(currency_code)s, %(expiry)s, %(source)s, '1day', %(bar_time)s,
            %(calls_oi)s, %(puts_oi)s, %(calls_puts_ratio)s, %(net_flow)s, %(query_used)s, %(region)s
        )
        ON CONFLICT (
            instrument_type, symbol, source, granularity, bar_time,
            COALESCE(contract_ticker, ''), COALESCE(expiry, ''), COALESCE(option_type, '')
        ) DO UPDATE SET
            calls_oi         = COALESCE(EXCLUDED.calls_oi,         fin_markets.quant_stats.calls_oi),
            puts_oi          = COALESCE(EXCLUDED.puts_oi,          fin_markets.quant_stats.puts_oi),
            calls_puts_ratio = COALESCE(EXCLUDED.calls_puts_ratio, fin_markets.quant_stats.calls_puts_ratio),
            net_flow         = COALESCE(EXCLUDED.net_flow,         fin_markets.quant_stats.net_flow),
            query_used       = COALESCE(EXCLUDED.query_used,       fin_markets.quant_stats.query_used),            currency_code    = COALESCE(EXCLUDED.currency_code,     fin_markets.quant_stats.currency_code),            region           = COALESCE(EXCLUDED.region,           fin_markets.quant_stats.region)
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
            obv, region
        ) VALUES (
            %(symbol)s, 'index', %(currency_code)s, %(source)s, %(granularity)s, %(bar_time)s,
            %(open)s, %(high)s, %(low)s, %(close)s, %(volume)s,
            %(sma_20)s, %(sma_50)s, %(sma_200)s, %(ema_12)s, %(ema_26)s,
            %(macd_line)s, %(macd_signal)s, %(macd_hist)s,
            %(rsi_14)s, %(stoch_k)s, %(stoch_d)s, %(willr_14)s, %(cci_20)s, %(roc_10)s,
            %(atr_14)s, %(bb_upper)s, %(bb_middle)s, %(bb_lower)s, %(natr_14)s,
            %(adx_14)s, %(plus_di_14)s, %(minus_di_14)s, %(aroon_up_14)s, %(aroon_down_14)s, %(sar)s,
            %(obv)s, %(region)s
        )
        ON CONFLICT (
            instrument_type, symbol, source, granularity, bar_time,
            COALESCE(contract_ticker, ''), COALESCE(expiry, ''), COALESCE(option_type, '')
        ) DO UPDATE SET
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
            region        = COALESCE(EXCLUDED.region,        fin_markets.quant_stats.region)
    """

    GET_COVERAGE = """
        SELECT MAX(bar_time) AS latest
        FROM fin_markets.quant_stats
        WHERE symbol = %s
          AND instrument_type = 'index'
          AND granularity = %s
          AND bar_time >= %s
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
