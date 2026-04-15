"""Transform raw OHLCV bars from quant_raw into quant_stats rows.

A single call may fuse bars from *multiple* quant_raw records (e.g. one
record for a 1-month window, another for a 1-year window) into one DataFrame
so that long-period indicators like SMA_200 have enough history.  Each bar in
the merged set produces exactly one ``quant_stats`` row.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

import pandas as pd

from backend.resource_api.quant_api.models import OHLCVBar

logger = logging.getLogger(__name__)

# ── Granularity mapping ────────────────────────────────────────────────────
# Maps yfinance interval strings → quant_stats CHECK-constrained values.
_INTERVAL_TO_GRANULARITY: dict[str, str] = {
    "1m":  "1min",
    "5m":  "5min",
    "15m": "15min",
    "30m": "30min",
    "60m": "1h",
    "1h":  "1h",
    "1d":  "1day",
    "1mo": "1mo",
}


def to_granularity(interval: str) -> str:
    """Map a yfinance interval string to an quant_stats granularity value."""
    return _INTERVAL_TO_GRANULARITY.get(interval, "1day")


def _safe(val: Any) -> float | None:
    """Return a finite float or None (converts NaN / inf / None safely)."""
    try:
        f = float(val)
        return None if (f != f or abs(f) > 1e15) else f  # NaN → None
    except (TypeError, ValueError):
        return None


def _merge_bars(bar_lists: list[list[OHLCVBar]]) -> list[OHLCVBar]:
    """Merge multiple bar lists into a single deduplicated, sorted list.

    When the same timestamp appears in more than one list the first
    occurrence wins (callers should pass more-authoritative data first).

    Args:
        bar_lists: One or more lists of OHLCVBar from different quant_raw
                   records (e.g. different period/interval combinations).

    Returns:
        Deduplicated, chronologically sorted list of bars.
    """
    seen: dict[str, OHLCVBar] = {}
    for bars in bar_lists:
        for bar in bars:
            if bar.date not in seen:
                seen[bar.date] = bar
    return sorted(seen.values(), key=lambda b: b.date)


# Pandas resample frequency strings for coarser storage intervals.
_RESAMPLE_FREQ: dict[str, str] = {
    "1d":  "1D",
    "1mo": "MS",   # month-start anchor
}


def resample_bars(bars: list[OHLCVBar], target_interval: str) -> list[OHLCVBar]:
    """Resample fine-grained OHLCV bars to a coarser target interval.

    Aggregation rules: open=first, high=max, low=min, close=last, volume=sum.
    Incomplete trailing periods (e.g. an open 4-hour bar with only 1 hour of
    data) are included — they will be overwritten on subsequent upserts as more
    fine-grained bars arrive.

    Args:
        bars:            Source bars at a finer interval (e.g. 1-hour bars).
        target_interval: Storage interval to resample to (e.g. ``"4h"``).

    Returns:
        Resampled bars at the target interval.  Returns ``bars`` unchanged if
        the target interval is not in ``_RESAMPLE_FREQ``.
    """
    freq = _RESAMPLE_FREQ.get(target_interval)
    if not freq or not bars:
        return bars

    df = pd.DataFrame(
        {
            "open":   [b.open          for b in bars],
            "high":   [b.high          for b in bars],
            "low":    [b.low           for b in bars],
            "close":  [b.close         for b in bars],
            "volume": [float(b.volume) for b in bars],
        },
        index=pd.to_datetime([b.date for b in bars], utc=True),
    )
    resampled = df.resample(freq).agg(
        {"open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum"}
    ).dropna(subset=["open", "close"])

    return [
        OHLCVBar(
            date=idx.isoformat(),
            open=round(float(row["open"]),   6),
            high=round(float(row["high"]),   6),
            low=round(float(row["low"]),     6),
            close=round(float(row["close"]), 6),
            volume=int(row["volume"]),
        )
        for idx, row in resampled.iterrows()
    ]


def compute_quant_stats(
    bar_lists: list[list[OHLCVBar]],
    symbol: str,
    source: str,
    interval: str = "1d",
) -> list[dict[str, Any]]:
    """Compute technical indicators from merged OHLCV bars.

    Accepts bars from *multiple* quant_raw records so that long-period
    indicators (SMA 200, etc.) can be computed even when the most-recent
    fetch only covers a short window.  Returns a list of dicts matching the
    ``fin_markets.quant_stats`` schema, ready for an upsert.

    Args:
        bar_lists: One or more chronologically ordered bar lists.  They are
                   merged and deduplicated before indicator computation.
        symbol:    Ticker symbol (e.g. ``'AAPL'``).
        source:    Data provider (e.g. ``'yfinance'``).
        interval:  yfinance-style interval string (e.g. ``'1d'``, ``'5m'``).

    Returns:
        List of row dicts — one per bar — with all indicator columns.
        Columns that cannot be computed (insufficient history) are ``None``.
    """
    bars = _merge_bars(bar_lists)
    if not bars:
        return []

    granularity = to_granularity(interval)

    df = pd.DataFrame(
        {
            "open":   [b.open          for b in bars],
            "high":   [b.high          for b in bars],
            "low":    [b.low           for b in bars],
            "close":  [b.close         for b in bars],
            "volume": [float(b.volume) for b in bars],
        },
        index=pd.to_datetime([b.date for b in bars], utc=True),
    )
    df.sort_index(inplace=True)

    # ── Compute indicators if pandas-ta is available ───────────────────────
    try:
        import pandas_ta as ta  # type: ignore[import]
    except ImportError:
        logger.warning(
            "pandas-ta not installed; quant_stats rows will have NULL indicators. "
            "Install with: pip install pandas-ta"
        )
        ta = None

    if ta is not None and len(df) >= 2:
        try:
            # Moving averages
            df.ta.sma(length=20,  append=True)
            df.ta.sma(length=50,  append=True)
            df.ta.sma(length=200, append=True)
            df.ta.ema(length=12,  append=True)
            df.ta.ema(length=26,  append=True)
            # MACD 12/26/9 → MACD_12_26_9, MACDh_12_26_9, MACDs_12_26_9
            df.ta.macd(fast=12, slow=26, signal=9, append=True)
            # Momentum
            df.ta.rsi(length=14,          append=True)  # RSI_14
            df.ta.stoch(k=14, d=3,        append=True)  # STOCHk_14_3_3, STOCHd_14_3_3
            df.ta.willr(length=14,        append=True)  # WILLR_14
            df.ta.cci(length=20,          append=True)  # CCI_20_0.015
            df.ta.mfi(length=14,          append=True)  # MFI_14
            df.ta.roc(length=10,          append=True)  # ROC_10
            # Volatility
            df.ta.atr(length=14,          append=True)  # ATRr_14
            df.ta.bbands(length=20, std=2, append=True) # BBL_20_2.0, BBM_20_2.0, BBU_20_2.0
            df.ta.natr(length=14,         append=True)  # NATR_14
            # Trend / DMI
            df.ta.adx(length=14,          append=True)  # ADX_14, DMP_14, DMN_14
            df.ta.aroon(length=14,        append=True)  # AROOND_14, AROONU_14
            df.ta.psar(append=True)                     # PSARl_0.02_0.2, PSARs_0.02_0.2
            # Volume
            df.ta.vwap(append=True)                     # VWAP_D
            df.ta.obv(append=True)                      # OBV
            df.ta.ad(append=True)                       # AD
        except Exception as exc:
            logger.warning("pandas-ta indicator computation failed: %s", exc)

    rows: list[dict[str, Any]] = []
    for idx, row in df.iterrows():
        bar_time: datetime = idx.to_pydatetime()
        if bar_time.tzinfo is None:
            bar_time = bar_time.replace(tzinfo=timezone.utc)

        # SAR: pandas-ta emits long (PSARl) and short (PSARs) signals on separate bars
        sar_val = _safe(row.get("PSARl_0.02_0.2")) or _safe(row.get("PSARs_0.02_0.2"))

        rows.append(
            {
                "symbol":        symbol.upper(),
                "source":        source,
                "granularity":   granularity,
                "bar_time":      bar_time,
                # ── OHLCV ────────────────────────────────────────────────
                "open":          _safe(row["open"]),
                "high":          _safe(row["high"]),
                "low":           _safe(row["low"]),
                "close":         _safe(row["close"]),
                "volume":        _safe(row["volume"]),
                "trade_count":   None,
                # ── Moving averages ──────────────────────────────────────
                "sma_20":        _safe(row.get("SMA_20")),
                "sma_50":        _safe(row.get("SMA_50")),
                "sma_200":       _safe(row.get("SMA_200")),
                "ema_12":        _safe(row.get("EMA_12")),
                "ema_26":        _safe(row.get("EMA_26")),
                # ── MACD ─────────────────────────────────────────────────
                "macd_line":     _safe(row.get("MACD_12_26_9")),
                "macd_signal":   _safe(row.get("MACDs_12_26_9")),
                "macd_hist":     _safe(row.get("MACDh_12_26_9")),
                # ── Momentum ─────────────────────────────────────────────
                "rsi_14":        _safe(row.get("RSI_14")),
                "stoch_k":       _safe(row.get("STOCHk_14_3_3")),
                "stoch_d":       _safe(row.get("STOCHd_14_3_3")),
                "willr_14":      _safe(row.get("WILLR_14")),
                "cci_20":        _safe(row.get("CCI_20_0.015")),
                "mfi_14":        _safe(row.get("MFI_14")),
                "roc_10":        _safe(row.get("ROC_10")),
                # ── Volatility ───────────────────────────────────────────
                "atr_14":        _safe(row.get("ATRr_14")),
                "bb_upper":      _safe(row.get("BBU_20_2.0")),
                "bb_middle":     _safe(row.get("BBM_20_2.0")),
                "bb_lower":      _safe(row.get("BBL_20_2.0")),
                "natr_14":       _safe(row.get("NATR_14")),
                # ── Trend / DMI ──────────────────────────────────────────
                "adx_14":        _safe(row.get("ADX_14")),
                "plus_di_14":    _safe(row.get("DMP_14")),
                "minus_di_14":   _safe(row.get("DMN_14")),
                "aroon_up_14":   _safe(row.get("AROONU_14")),
                "aroon_down_14": _safe(row.get("AROOND_14")),
                "sar":           sar_val,
                # ── Volume ───────────────────────────────────────────────
                "vwap":          _safe(row.get("VWAP_D")),
                "obv":           _safe(row.get("OBV")),
                "ad":            _safe(row.get("AD")),
            }
        )

    logger.debug(
        "compute_quant_stats: symbol=%s source=%s granularity=%s bars=%d rows=%d",
        symbol, source, granularity, len(bars), len(rows),
    )
    return rows
