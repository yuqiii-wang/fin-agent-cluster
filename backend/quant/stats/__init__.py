"""Quant stats — pandas-based OHLCV computation utilities.

Sub-modules
-----------
dataframe    — :func:`matrix_to_split` and :func:`split_to_dataframe` for
               converting between ``OhlcvStatsMatrix`` and the split-orient dict.
metrics      — :func:`compute_metrics` for vectorised OHLCV metric computation.
indicators   — :func:`build_ohlcv_dataframe`, :func:`build_indicator_df`, and
               :func:`safe_float` for ``pandas_ta``-based indicator computation.
correlation  — :func:`compute_pearson_matrix` for Pearson correlation of
               aligned Series (close prices, SMAs, EMAs, etc.).

Market data models and the HTTP client live in
:mod:`backend.resources.stats`.
"""

from __future__ import annotations

from backend.quant.stats.dataframe import matrix_to_split, split_to_dataframe
from backend.quant.stats.metrics import compute_metrics
from backend.quant.stats.indicators import safe_float, build_ohlcv_dataframe, build_indicator_df
from backend.quant.stats.correlation import compute_pearson_matrix
from backend.quant.stats.constants import STATS_DATA_TYPE, STATS_VIEW_TYPE, OHLCV, OPTIONS, FUTURES, TEXT, FUNDAMENTALS

__all__ = [
    "matrix_to_split",
    "split_to_dataframe",
    "compute_metrics",
    "safe_float",
    "build_ohlcv_dataframe",
    "build_indicator_df",
    "compute_pearson_matrix",
    "STATS_DATA_TYPE",
    "STATS_VIEW_TYPE",
    "OHLCV",
    "OPTIONS",
    "FUTURES",
    "TEXT",
    "FUNDAMENTALS",
]
