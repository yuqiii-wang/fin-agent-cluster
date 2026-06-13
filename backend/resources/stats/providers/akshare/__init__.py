"""akshare stats provider sub-package.

Fetches OHLCV data for China A-share markets (Shanghai ``*.SS`` and
Shenzhen ``*.SZ`` tickers) via the ``akshare`` library.
"""

from __future__ import annotations

from backend.resources.stats.providers.akshare.fetcher import fetch
from backend.resources.stats.providers.akshare.transformer import PERIOD_MAP, strip_suffix, transform

__all__ = ["fetch", "PERIOD_MAP", "strip_suffix", "transform"]
