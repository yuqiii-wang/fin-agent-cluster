"""OHLCV metric computations using vectorised pandas operations.

All functions operate on the split-orient DataFrame dict produced by
:func:`~backend.quant.stats.dataframe.matrix_to_split` so that the
computation layer is decoupled from the HTTP transport format.
"""

from __future__ import annotations

__all__ = ["compute_metrics"]


def compute_metrics(df_split: dict) -> dict:
    """Derive key OHLCV metrics from a pandas split-orient DataFrame dict.

    Reconstructs the DataFrame via
    :func:`~backend.quant.stats.dataframe.split_to_dataframe`, then uses
    vectorised pandas operations for all metric computations.

    Metrics computed
    ----------------
    * ``return_pct``  — period return ``(last_close - first_close) / first_close * 100``.
    * ``volatility``  — standard deviation of daily returns, expressed as a percentage.
    * ``trend``       — ``"uptrend"`` / ``"downtrend"`` / ``"sideways"`` derived by
                        comparing the mean of the last third of closes against the
                        first third (±1 % threshold).
    * ``bar_count``   — number of OHLCV bars in the series.
    * ``first_close`` — first closing price.
    * ``last_close``  — last closing price.

    Args:
        df_split: Dict with keys ``"index"``, ``"columns"``, ``"data"``
                  as produced by :func:`~backend.quant.stats.dataframe.matrix_to_split`.

    Returns:
        Dict containing the metrics listed above.  Returns zeroed/unknown
        values when the DataFrame is empty or has fewer than two bars.
    """
    from backend.quant.stats.dataframe import split_to_dataframe

    if not df_split or not df_split.get("data"):
        return {"return_pct": 0.0, "volatility": 0.0, "trend": "unknown", "bar_count": 0}

    df = split_to_dataframe(df_split)

    if "close" not in df.columns or len(df) < 2:
        return {"return_pct": 0.0, "volatility": 0.0, "trend": "unknown", "bar_count": len(df)}

    closes = df["close"]
    period_return = (closes.iloc[-1] - closes.iloc[0]) / closes.iloc[0] * 100
    daily_returns = closes.pct_change().dropna()
    volatility = float(daily_returns.std() * 100) if len(daily_returns) > 1 else 0.0

    third = max(1, len(closes) // 3)
    early_avg = closes.iloc[:third].mean()
    late_avg = closes.iloc[-third:].mean()
    if late_avg > early_avg * 1.01:
        trend = "uptrend"
    elif late_avg < early_avg * 0.99:
        trend = "downtrend"
    else:
        trend = "sideways"

    return {
        "return_pct": round(float(period_return), 4),
        "volatility": round(volatility, 4),
        "trend": trend,
        "bar_count": len(closes),
        "first_close": round(float(closes.iloc[0]), 4),
        "last_close": round(float(closes.iloc[-1]), 4),
    }
