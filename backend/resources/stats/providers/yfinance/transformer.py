"""yfinance stats provider -- transform yfinance DataFrame into StatsRecord.

yfinance returns a ``pandas.DataFrame`` from ``yf.Ticker(symbol).history(period, interval)``.

Columns present (may vary by interval):
    Open, High, Low, Close, Volume, Dividends, Stock Splits

The transformer:
  * Drops the tz-offset from the DatetimeIndex and converts to ISO-8601 date strings.
  * Maps standard OHLCV columns to lower-case series keys.
  * Drops ``Dividends`` and ``Stock Splits`` (not part of OhlcvStatsMatrix convention).
  * Skips any column that is entirely NaN.

Period / interval mapping
--------------------------
yfinance ``period`` and ``interval`` args accepted by :func:`fetch`:

+--------+------------------------------+
| period | interval (default)           |
+========+==============================+
| ``1d`` | ``1h``                       |
| ``1w`` | ``1d``                       |
| ``1mo``| ``1d``                       |
| ``3mo``| ``1wk``                      |
| ``1y`` | ``1wk``                      |
| ``2y`` | ``1d``                       |
+--------+------------------------------+
"""

from __future__ import annotations

import hashlib

from backend.resources.stats.models import OhlcvStatsMatrix, StatsRecord

# Maps our period labels to (yfinance_period, yfinance_interval)
_PERIOD_MAP: dict[str, tuple[str, str]] = {
    "1d":  ("5d",  "1h"),
    "1w":  ("1mo", "1d"),
    "1mo": ("3mo", "1d"),
    "3mo": ("6mo", "1wk"),
    "1y":  ("2y",  "1wk"),
    "2y":  ("2y",  "1d"),
}

# yfinance column name -> OhlcvStatsMatrix series key
_COL_MAP: dict[str, str] = {
    "Open":   "open",
    "High":   "high",
    "Low":    "low",
    "Close":  "close",
    "Volume": "volume",
}


def _record_id(symbol: str, period: str) -> str:
    """Generate a deterministic record ID from symbol + period."""
    return f"yf-{symbol.lower()}-{period}"


def transform(
    symbol: str,
    period: str,
    df: "pandas.DataFrame",  # type: ignore[name-defined]  # noqa: F821
) -> StatsRecord:
    """Transform a yfinance ``history()`` DataFrame into a :class:`StatsRecord`.

    Args:
        symbol: Equity ticker used in the fetch, e.g. ``"AAPL"``.
        period: Aggregation period label, e.g. ``"1d"``.
        df:     DataFrame returned by ``yf.Ticker(symbol).history(...)``.
                Must have a ``DatetimeIndex`` and at least one OHLCV column.

    Returns:
        A :class:`~backend.resources.stats.models.StatsRecord` with
        ``content.timestamps`` as the x-axis and each OHLCV column as a
        named series in ``content.series``.

    Raises:
        ValueError: If ``df`` is empty or has no recognisable OHLCV columns.
    """
    if df.empty:
        raise ValueError(f"yfinance returned empty DataFrame for {symbol!r} period={period!r}")

    # Normalise index to plain date strings (drop tz info)
    index = df.index
    try:
        index = index.tz_localize(None)
    except TypeError:
        index = index.tz_convert(None)
    timestamps: list[str] = [ts.strftime("%Y-%m-%d") for ts in index]

    series: dict[str, list[float]] = {}
    for col, key in _COL_MAP.items():
        if col not in df.columns:
            continue
        column = df[col].dropna()
        if column.empty:
            continue
        # Re-align to full index, filling missing with NaN then 0.0
        aligned = df[col].reindex(df.index).fillna(0.0)
        series[key] = [float(v) for v in aligned]

    if not series:
        raise ValueError(f"No recognisable OHLCV columns in yfinance DataFrame for {symbol!r}")

    return StatsRecord(
        id=_record_id(symbol, period),
        symbol=symbol.upper(),
        period=period,
        content=OhlcvStatsMatrix(timestamps=timestamps, series=series).model_dump(),
    )


def period_args(period: str) -> tuple[str, str]:
    """Return the ``(yf_period, yf_interval)`` args for a given period label.

    Args:
        period: One of ``1d``, ``1w``, ``1mo``, ``3mo``, ``1y``.

    Returns:
        Tuple of ``(yfinance_period, yfinance_interval)`` strings.

    Raises:
        ValueError: If the period is not in the supported set.
    """
    if period not in _PERIOD_MAP:
        raise ValueError(
            f"Unsupported period {period!r}. Supported: {sorted(_PERIOD_MAP)}"
        )
    return _PERIOD_MAP[period]
