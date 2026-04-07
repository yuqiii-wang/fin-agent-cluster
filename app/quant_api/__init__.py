"""Quant API client layer — swappable external market data providers.

Available providers:
  - FMPClient: Financial Modeling Prep (requires API key)
  - YFinanceClient: Yahoo Finance via yfinance (no API key required)

Agent-facing entry point:
  - MarketDataService: unified fetch + normalise + DB ingest, provider-agnostic
"""

from app.quant_api.base import QuantAPIBase
from app.quant_api.fmp import FMPClient
from app.quant_api.service import MarketDataService, ProviderType
from app.quant_api.yfinance_client import YFinanceClient

__all__ = ["QuantAPIBase", "FMPClient", "YFinanceClient", "MarketDataService", "ProviderType"]
