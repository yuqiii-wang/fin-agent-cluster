"""yfinance stats provider package.

Exports
-------
fetch       -- async download + transform into StatsRecord.
transform   -- transform a yfinance DataFrame into a StatsRecord.
period_args -- map a period label to (yf_period, yf_interval) args.
"""

from __future__ import annotations

from backend.resources.stats.providers.yfinance.fetch_options import fetch_options
from backend.resources.stats.providers.yfinance.fetcher import fetch
from backend.resources.stats.providers.yfinance.transformer import period_args, transform

__all__ = ["fetch", "fetch_options", "transform", "period_args"]
