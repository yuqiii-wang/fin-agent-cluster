"""akshare stats provider -- transform akshare DataFrames into StatsRecord.

akshare returns ``pandas.DataFrame`` objects from calls such as:

* ``ak.stock_zh_a_hist(symbol, period, start_date, end_date, adjust)``
  for daily / weekly aggregation of A-share stocks.
* ``ak.stock_zh_a_hist_min_em(symbol, period, start_date, end_date)``
  for intraday (60-minute) bars.

Column mapping (daily / weekly)
---------------------------------
akshare Chinese column -> OhlcvStatsMatrix series key
``开盘``  (open)       -> ``open``
``收盘``  (close)      -> ``close``
``最高``  (high)       -> ``high``
``最低``  (low)        -> ``low``
``成交量`` (volume)    -> ``volume``

Column mapping (intraday)
--------------------------
``开盘``  (open)       -> ``open``
``收盘``  (close)      -> ``close``
``最高``  (high)       -> ``high``
``最低``  (low)        -> ``low``
``成交量`` (volume)    -> ``volume``

The timestamp column is ``日期`` for daily/weekly and ``时间`` for intraday.

Period / akshare parameter mapping
-----------------------------------
+--------+------------------+------------------+
| period | akshare period   | days_back        |
+========+==================+==================+
| ``1d`` | intraday 60-min  | 5                |
| ``1w`` | ``daily``        | 30               |
| ``1mo``| ``daily``        | 90               |
| ``3mo``| ``weekly``       | 180              |
| ``1y`` | ``weekly``       | 730              |
| ``2y`` | ``daily``        | 730              |
+--------+------------------+------------------+
"""

from __future__ import annotations

from backend.resources.stats.models import OhlcvStatsMatrix, StatsRecord

# Maps period labels to (akshare_period_or_"intraday", days_back)
PERIOD_MAP: dict[str, tuple[str, int]] = {
    "1d":  ("intraday", 5),
    "1w":  ("daily",    30),
    "1mo": ("daily",    90),
    "3mo": ("weekly",   180),
    "1y":  ("weekly",   730),
    "2y":  ("daily",    730),
}

# Column maps: akshare Chinese column names -> OhlcvStatsMatrix series key
_OHLCV_COLS: dict[str, str] = {
    "开盘":  "open",
    "收盘":  "close",
    "最高":  "high",
    "最低":  "low",
    "成交量": "volume",
}

_DATE_COL_DAILY = "日期"
_DATE_COL_INTRADAY = "时间"


def strip_suffix(symbol: str) -> str:
    """Convert a yfinance-style ticker to an akshare 6-digit A-share code.

    Args:
        symbol: e.g. ``"600519.SS"`` or ``"000858.SZ"``.

    Returns:
        Six-digit code string, e.g. ``"600519"`` or ``"000858"``.
    """
    return symbol.split(".")[0]


def _record_id(symbol: str, period: str) -> str:
    """Generate a deterministic record ID from symbol + period."""
    return f"ak-{symbol.lower()}-{period}"


def transform(
    symbol: str,
    period: str,
    df: "pandas.DataFrame",  # type: ignore[name-defined]  # noqa: F821
    *,
    intraday: bool = False,
) -> StatsRecord:
    """Transform an akshare history DataFrame into a :class:`StatsRecord`.

    Args:
        symbol:   Original ticker with suffix, e.g. ``"600519.SS"``.
        period:   Aggregation period label, e.g. ``"1d"``.
        df:       DataFrame returned by akshare.  Must contain the expected
                  Chinese column names and a date/time column.
        intraday: ``True`` when ``df`` comes from ``stock_zh_a_hist_min_em``
                  (uses ``时间`` as the timestamp column).

    Returns:
        A :class:`~backend.resources.stats.models.StatsRecord`.

    Raises:
        ValueError: If ``df`` is empty or has no recognisable OHLCV columns.
    """
    if df.empty:
        raise ValueError(f"akshare returned empty DataFrame for symbol={symbol} period={period}")

    date_col = _DATE_COL_INTRADAY if intraday else _DATE_COL_DAILY

    timestamps: list[str] = df[date_col].astype(str).tolist()

    series: dict[str, list[float]] = {}
    for cn_col, series_key in _OHLCV_COLS.items():
        if cn_col in df.columns:
            series[series_key] = df[cn_col].astype(float).tolist()

    if not series:
        raise ValueError(
            f"akshare DataFrame for symbol={symbol} period={period} has no recognisable OHLCV columns"
        )

    return StatsRecord(
        id=_record_id(symbol, period),
        symbol=symbol,
        period=period,
        content=OhlcvStatsMatrix(timestamps=timestamps, series=series).model_dump(),
    )


__all__ = ["PERIOD_MAP", "strip_suffix", "transform"]
