"""Pearson correlation computation for aligned OHLCV and indicator series.

Provides :func:`compute_pearson_matrix` which aligns multiple named
:class:`~pandas.Series` by index (inner join), trims to the requested
lookback window, and returns the full Pearson correlation matrix as a
nested dict.

Series with insufficient overlap (fewer than :data:`_MIN_BARS` aligned bars)
result in an empty matrix — the caller decides whether to raise or skip.
"""

from __future__ import annotations

import pandas as pd

__all__ = ["compute_pearson_matrix"]

_MIN_BARS: int = 2


def compute_pearson_matrix(
    series_map: dict[str, pd.Series],
    window_bars: int,
) -> tuple[dict[str, dict[str, float]], int]:
    """Compute the Pearson correlation matrix for a set of aligned Series.

    Series are aligned by index using an inner join; rows with any ``NaN``
    are dropped.  The combined frame is then trimmed to the most-recent
    *window_bars* rows before computing correlations.

    Args:
        series_map:  Mapping of label → :class:`pandas.Series` with a common
                     DatetimeIndex.  Series that are empty are ignored;
                     fewer than 2 non-empty Series returns an empty result.
        window_bars: Maximum number of most-recent aligned bars to include.

    Returns:
        A tuple ``(matrix, bar_count)`` where *matrix* is a nested
        ``{label → {label → pearson_r}}`` dict (values rounded to 6 d.p.)
        and *bar_count* is the number of aligned bars used.
        Returns ``({}, 0)`` when fewer than :data:`_MIN_BARS` aligned bars
        exist after inner-join and trimming.
    """
    non_empty = {name: s for name, s in series_map.items() if not s.empty}
    if len(non_empty) < 2:
        return {}, 0

    combined = pd.DataFrame(non_empty).dropna(how="any")
    if len(combined) > window_bars:
        combined = combined.iloc[-window_bars:]

    if len(combined) < _MIN_BARS:
        return {}, 0

    corr_df = combined.corr(method="pearson")
    matrix: dict[str, dict[str, float]] = {
        col: {row: round(float(corr_df.loc[row, col]), 6) for row in corr_df.index}
        for col in corr_df.columns
    }
    return matrix, len(combined)
