"""Quant — quantitative analysis layer.

Sub-packages
------------
stats  — pandas-based OHLCV computation utilities (DataFrame conversion,
         metric calculations).  Market data models and HTTP clients live in
         :mod:`backend.resources.stats`.
"""

from __future__ import annotations

from backend.quant.stats import compute_metrics, matrix_to_split, split_to_dataframe

__all__ = [
    "compute_metrics",
    "matrix_to_split",
    "split_to_dataframe",
]
