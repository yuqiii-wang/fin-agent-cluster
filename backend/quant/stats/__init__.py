"""Quant stats — pandas-based OHLCV computation utilities.

Sub-modules
-----------
dataframe  — :func:`matrix_to_split` and :func:`split_to_dataframe` for
             converting between ``StatsMatrix`` and the split-orient dict.
metrics    — :func:`compute_metrics` for vectorised OHLCV metric computation.

Market data models and the HTTP client live in
:mod:`backend.resources.stats`.
"""

from __future__ import annotations

from backend.quant.stats.dataframe import matrix_to_split, split_to_dataframe
from backend.quant.stats.metrics import compute_metrics

__all__ = [
    "matrix_to_split",
    "split_to_dataframe",
    "compute_metrics",
]
