"""provider_chain — period and provider fallback constants and builder for get_stats."""

from __future__ import annotations

from backend.config import get_settings
from backend.resources.stats.routing import provider_for_symbol

# Ordered fallback chain: if the requested period returns no data, try the next shorter period.
PERIOD_FALLBACKS: dict[str, list[str]] = {
    "2y": ["1y"],
    "1y": ["3mo"],
    "3mo": ["1mo"],
    "1mo": ["1w"],
    "1w": ["1d"],
}

# Kept for calculate_corr parity.
MIN_BARS_FOR_CORR: int = 2

# Ordered provider fallback chains: when the primary provider returns no data,
# the next provider in the list is tried before giving up.
_PROVIDER_FALLBACK_CHAINS: dict[str, list[str]] = {
    "fmp": ["fmp", "yfinance"],
    "yfinance": ["yfinance", "fmp"],
    "mock": ["mock"],
}


def build_provider_chain(symbol: str) -> list[str]:
    """Return the ordered list of stats providers to try for *symbol*.

    The primary provider is resolved from ticker-suffix routing, then the
    remaining chain entries from :data:`_PROVIDER_FALLBACK_CHAINS` are
    appended.  ``fmp`` is excluded from the chain when ``FMP_API_KEY`` is
    not configured.

    Args:
        symbol: Normalised (uppercase) ticker symbol.

    Returns:
        Non-empty list of provider labels in priority order.
    """
    settings = get_settings()
    primary = provider_for_symbol(symbol) or (settings.STATS_PROVIDER or "mock").strip().lower()
    chain = _PROVIDER_FALLBACK_CHAINS.get(primary, [primary])
    if not settings.FMP_API_KEY:
        chain = [p for p in chain if p != "fmp"]
    return chain or ["mock"]


__all__ = ["PERIOD_FALLBACKS", "MIN_BARS_FOR_CORR", "build_provider_chain"]
