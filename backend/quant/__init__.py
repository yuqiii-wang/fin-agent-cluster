"""Quant — quantitative analysis layer.

Sub-packages
------------
stats                  — pandas-based OHLCV computation utilities (DataFrame conversion,
                         metric calculations, indicator computation, Pearson correlation).
                         Market data models and HTTP clients live in :mod:`backend.resources.stats`.
instrument_types       — instrument type literals and symbol-to-type resolution.
field_name_conversion  — generic field-name normalisation to snake_case; percent-string coercion.
"""

from __future__ import annotations

from backend.quant.field_name_conversion import (
    to_snake_case,
    normalize_keys,
    coerce_numeric,
)
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
    "to_snake_case",
    "normalize_keys",
    "coerce_numeric",
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
