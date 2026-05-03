"""FMP (Financial Modeling Prep) stats provider package.

Exports
-------
fetch     — async download + transform into StatsRecord.
transform — transform an FMP JSON response into a StatsRecord.
"""

from __future__ import annotations

from backend.resources.stats.fmp.fetcher import fetch
from backend.resources.stats.fmp.transformer import transform

__all__ = ["fetch", "transform"]
