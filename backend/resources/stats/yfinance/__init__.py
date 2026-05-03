"""yfinance stats provider package.

Exports
-------
fetch       — async download + transform into StatsRecord.
transform   — transform a yfinance DataFrame into a StatsRecord.
period_args — map a period label to (yf_period, yf_interval) args.
"""

from __future__ import annotations

from backend.resources.stats.yfinance.fetcher import fetch
from backend.resources.stats.yfinance.transformer import period_args, transform

__all__ = ["fetch", "transform", "period_args"]
