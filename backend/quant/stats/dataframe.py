"""Pandas DataFrame utilities for OHLCV stats data.

Converts between the ``OhlcvStatsMatrix`` wire format and pandas DataFrames,
and serialises DataFrames to the split orient for compact HTTP transport.

Split-orient format
-------------------
``pd.DataFrame.to_dict(orient="split")`` produces::

    {
        "index":   ["2026-01-01", "2026-01-02", ...],
        "columns": ["open", "high", "low", "close", "volume", ...],
        "data":    [[172.5, 175.3, 171.8, 174.2, 72400000], ...],
    }

This is the canonical representation used throughout the quant pipeline:
``read_stats`` serialises to it; ``analyze_stats`` reconstructs from it.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import pandas as pd
    from backend.resources.stats.models import OhlcvStatsMatrix

__all__ = ["matrix_to_split", "split_to_dataframe"]


def matrix_to_split(matrix: "OhlcvStatsMatrix") -> dict:
    """Convert a :class:`~backend.resources.stats.models.OhlcvStatsMatrix` to a pandas split-orient dict.

    Builds a DataFrame with a ``DatetimeIndex`` from ``matrix.timestamps``
    and one column per series in ``matrix.series``, then serialises to
    split orient with ISO-8601 date strings as the index.

    Args:
        matrix: Time-series matrix with ``timestamps`` (x-axis) and
                ``series`` (named OHLCV columns).

    Returns:
        Dict with keys ``"index"``, ``"columns"``, ``"data"`` suitable for
        direct JSON serialisation and reconstruction via
        :func:`split_to_dataframe`.
    """
    import pandas as pd

    df = pd.DataFrame(matrix.series, index=pd.DatetimeIndex(matrix.timestamps))
    df.index.name = "timestamp"

    raw = df.to_dict(orient="split")
    return {
        "index": [str(ts)[:10] for ts in raw["index"]],
        "columns": raw["columns"],
        "data": raw["data"],
    }


def split_to_dataframe(df_split: dict) -> "pd.DataFrame":
    """Reconstruct a pandas DataFrame from a split-orient dict.

    Args:
        df_split: Dict with keys ``"index"``, ``"columns"``, ``"data"``
                  as produced by :func:`matrix_to_split`.

    Returns:
        :class:`pandas.DataFrame` with a ``DatetimeIndex``.
    """
    import pandas as pd

    return pd.DataFrame(
        data=df_split.get("data", []),
        index=pd.DatetimeIndex(df_split.get("index", [])),
        columns=df_split.get("columns", []),
    )
