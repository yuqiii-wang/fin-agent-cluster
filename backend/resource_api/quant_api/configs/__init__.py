"""Configuration package for the quant market-data API.

Each sub-module holds one concern:
  periods       — PERIOD_DAYS, OhlcvWindow, OHLCV_WINDOWS, AUX_DAILY_WINDOW
  sources       — QUANT_SOURCE_DEFAULTS (region → ordered provider list)
  index_labels  — INDEX_LABEL_TICKER_MAP (human label → canonical ticker)
  macro_symbols — MACRO_SYMBOLS, BOND_TENORS
  ticker_maps/  — per-provider TICKER_MAP dicts
"""

from backend.resource_api.quant_api.configs.periods import (
    PERIOD_DAYS,
    OhlcvWindow,
    OHLCV_WINDOWS,
    AUX_DAILY_WINDOW,
)
from backend.resource_api.quant_api.configs.sources import QUANT_SOURCE_DEFAULTS
from backend.resource_api.quant_api.configs.index_labels import INDEX_LABEL_TICKER_MAP
from backend.resource_api.quant_api.configs.macro_symbols import MACRO_SYMBOLS, BOND_TENORS

__all__ = [
    "PERIOD_DAYS",
    "OhlcvWindow",
    "OHLCV_WINDOWS",
    "AUX_DAILY_WINDOW",
    "QUANT_SOURCE_DEFAULTS",
    "INDEX_LABEL_TICKER_MAP",
    "MACRO_SYMBOLS",
    "BOND_TENORS",
]
