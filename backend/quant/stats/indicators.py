"""OHLCV technical indicator computation using ``pandas_ta``.

Provides :func:`build_ohlcv_dataframe` to reconstruct a DatetimeIndex
DataFrame from a :class:`~backend.resources.stats.models.OhlcvStatsMatrix`, and
:func:`build_indicator_df` to append the full suite of technical indicators
supported by ``fin_markets.quant_stats``.

Indicator coverage (mirrors ``quant_stats`` schema columns)
------------------------------------------------------------
Moving averages : SMA 20 / 50 / 200, EMA 12 / 26
MACD (12/26/9)  : line, signal, histogram
Momentum        : RSI-14, Stochastic %K/%D (14/3/3), Williams %R-14,
                  CCI-20, MFI-14, ROC-10
Volatility      : ATR-14, Bollinger Bands (20, 2σ), Normalized ATR-14
Trend / ADX     : ADX-14, +DI-14, -DI-14, Aroon Up/Down-14, Parabolic SAR
Volume          : VWAP, OBV, Chaikin A/D Line

Indicators that require more history than the DataFrame contains are silently
left as ``NaN`` — callers should propagate these as ``None`` to the database.
"""

from __future__ import annotations

import math
from datetime import datetime, timezone
from typing import TYPE_CHECKING

import pandas as pd

if TYPE_CHECKING:
    from backend.resources.stats.models import OhlcvStatsMatrix

__all__ = ["safe_float", "build_ohlcv_dataframe", "build_indicator_df"]


def safe_float(val: object) -> float | None:
    """Return a finite float or ``None`` for NaN / None / non-numeric values.

    Args:
        val: Any value to coerce.

    Returns:
        Python ``float`` when *val* is a finite number, otherwise ``None``.
    """
    if val is None:
        return None
    try:
        f = float(val)
        return None if math.isnan(f) or math.isinf(f) else f
    except (TypeError, ValueError):
        return None


def _parse_bar_time(ts: str) -> datetime:
    """Parse an ISO-8601 timestamp string to a timezone-aware UTC datetime.

    Handles date-only strings (``'2026-01-01'``) and full datetime strings
    (``'2026-01-01T09:00:00'``, ``'2026-01-01 09:00:00'``).

    Args:
        ts: ISO-8601 date or datetime string.

    Returns:
        Timezone-aware UTC :class:`datetime`.
    """
    ts = ts.replace("Z", "+00:00")
    if len(ts) <= 10:
        dt = datetime.strptime(ts[:10], "%Y-%m-%d")
    else:
        dt = datetime.fromisoformat(ts)
    return dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt.astimezone(timezone.utc)


def build_ohlcv_dataframe(matrix: "OhlcvStatsMatrix") -> pd.DataFrame:
    """Build a DatetimeIndex OHLCV DataFrame from a :class:`OhlcvStatsMatrix`.

    Args:
        matrix: Time-series matrix with ``timestamps`` (x-axis) and
                ``series`` (named OHLCV columns).

    Returns:
        :class:`pandas.DataFrame` with a UTC-aware :class:`~pandas.DatetimeIndex`
        named ``"timestamp"`` and columns matching ``matrix.series`` keys.
    """
    bar_times = [_parse_bar_time(ts) for ts in matrix.timestamps]
    df = pd.DataFrame(matrix.series, index=pd.DatetimeIndex(bar_times))
    df.index.name = "timestamp"
    return df


def build_indicator_df(df: pd.DataFrame) -> pd.DataFrame:
    """Append all ``quant_stats`` technical indicator columns to *df* using ``pandas_ta``.

    Operates in-place on *df*.  Indicators requiring more history than *df*
    contains produce ``NaN`` columns, which the caller should map to ``None``
    before writing to the database.

    Args:
        df: OHLCV DataFrame with a :class:`~pandas.DatetimeIndex` and columns
            ``open``, ``high``, ``low``, ``close``, ``volume``.

    Returns:
        The same DataFrame with all indicator columns appended.
    """
    import pandas_ta as ta  # noqa: F401 — registers the .ta accessor

    # Moving averages
    df.ta.sma(20, append=True)
    df.ta.sma(50, append=True)
    df.ta.sma(200, append=True)
    df.ta.ema(12, append=True)
    df.ta.ema(26, append=True)

    # MACD (12/26/9)
    df.ta.macd(fast=12, slow=26, signal=9, append=True)

    # Momentum
    df.ta.rsi(14, append=True)
    df.ta.stoch(k=14, d=3, smooth_k=3, append=True)
    df.ta.willr(14, append=True)
    df.ta.cci(20, append=True)
    df.ta.mfi(14, append=True)
    df.ta.roc(10, append=True)

    # Volatility
    df.ta.atr(14, append=True)
    df.ta.bbands(length=20, std=2.0, append=True)
    df.ta.natr(14, append=True)

    # Trend / ADX family
    df.ta.adx(14, append=True)
    df.ta.aroon(14, append=True)
    df.ta.psar(af0=0.02, af=0.02, max_af=0.2, append=True)

    # Volume / price-volume
    df.ta.vwap(append=True)
    df.ta.obv(append=True)
    df.ta.ad(append=True)

    return df
