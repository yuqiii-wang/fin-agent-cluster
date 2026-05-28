"""Quant — quantitative analysis layer.

Sub-packages
------------
stats            — pandas-based OHLCV computation utilities (DataFrame conversion,
                   metric calculations, indicator computation, Pearson correlation).
                   Market data models and HTTP clients live in :mod:`backend.resources.stats`.
instrument_types — instrument type literals and symbol-to-type resolution.
"""

from __future__ import annotations

from backend.quant.instrument_types import (
    InstrumentType,
    INSTRUMENT_TYPES,
    resolve_instrument_type,
)
from backend.quant.stats import (
    compute_metrics,
    matrix_to_split,
    split_to_dataframe,
    safe_float,
    build_ohlcv_dataframe,
    build_indicator_df,
    compute_pearson_matrix,
)

__all__ = [
    "InstrumentType",
    "INSTRUMENT_TYPES",
    "resolve_instrument_type",
    "compute_metrics",
    "matrix_to_split",
    "split_to_dataframe",
    "safe_float",
    "build_ohlcv_dataframe",
    "build_indicator_df",
    "compute_pearson_matrix",
]
