"""URL templates for supported web-knowledge page types.

Each entry maps a :class:`~backend.resources.web_knowledge.models.WebPageType`
to a callable that builds the canonical URL from the given symbol and optional
exchange.

URL patterns
------------
* competitors   -- ``https://www.marketbeat.com/stocks/{EXCHANGE}/{SYMBOL}/competitors-and-alternatives/``
* press_releases -- ``https://www.nasdaq.com/market-activity/stocks/{symbol}/press-releases``
* option_chain  -- ``https://www.nasdaq.com/market-activity/stocks/{symbol}/option-chain``

yfinance exchange code -> MarketBeat exchange name mapping
----------------------------------------------------------
yfinance returns short codes such as ``'NMS'`` (NASDAQ National Market Select) or
``'NYQ'`` (NYSE).  MarketBeat URLs require the human-readable exchange name.
Use :func:`yf_exchange_to_marketbeat` to convert before calling ``build_url``.
"""

from __future__ import annotations

from typing import Callable

from backend.resources.web_knowledge.errors import WK_EXCHANGE_REQUIRED
from backend.resources.web_knowledge.models import WebPageType

# ---------------------------------------------------------------------------
# yfinance exchange code -> MarketBeat URL exchange name
# ---------------------------------------------------------------------------

_YF_EXCHANGE_TO_MARKETBEAT: dict[str, str] = {
    # US -- NASDAQ
    "NMS": "NASDAQ",    # NASDAQ National Market Select
    "NNM": "NASDAQ",    # NASDAQ National Market
    "NGM": "NASDAQ",    # NASDAQ Global Market
    "NCM": "NASDAQ",    # NASDAQ Capital Market
    "BTS": "NASDAQ",    # NASDAQ BGS / BATS
    # US -- NYSE
    "NYQ": "NYSE",
    "NYSE": "NYSE",
    # US -- NYSE Arca / AMEX
    "PCX": "NYSEARCA",
    "ARCA": "NYSEARCA",
    "ASE": "NYSEAMERICAN",
    "AMEX": "NYSEAMERICAN",
    # International
    "HKG": "HKEX",
    "HKS": "HKEX",
    "LSE": "LSE",
    "GER": "XETRA",
    "FRA": "FRA",
    "PAR": "PAR",
    "AMS": "AMS",
    "SWX": "SWX",
    "TOR": "TSX",
    "TSX": "TSX",
    "TYO": "TYO",
    "KSC": "KSC",
    "KSQ": "KSQ",
    "ASX": "ASX",
    "SHH": "SHH",
    "SHZ": "SHZ",
    "NSI": "NSE",
    "BOM": "BSE",
    "SAO": "BVSP",
    "SGX": "SGX",
    "IDX": "IDX",
}


def yf_exchange_to_marketbeat(yf_exchange: str) -> str | None:
    """Map a yfinance exchange code to the corresponding MarketBeat exchange name.

    Args:
        yf_exchange: Exchange code returned by ``yfinance``, e.g. ``'NMS'``, ``'NYQ'``, ``'HKG'``.

    Returns:
        MarketBeat-compatible exchange name string (e.g. ``'NASDAQ'``, ``'NYSE'``),
        or ``None`` when the code is not in the mapping.
    """
    return _YF_EXCHANGE_TO_MARKETBEAT.get(yf_exchange.upper())


def _competitors_url(symbol: str, exchange: str | None) -> str:
    """Build the MarketBeat competitors-and-alternatives URL.

    Args:
        symbol:   Equity ticker, e.g. ``'AAPL'``.
        exchange: Exchange the ticker is listed on, e.g. ``'NASDAQ'`` or ``'NYSE'``.

    Returns:
        Fully qualified MarketBeat competitors page URL.

    Raises:
        ValueError: When *exchange* is not supplied.
    """
    if not exchange:
        raise ValueError(f"[{WK_EXCHANGE_REQUIRED}] exchange is required for page_type=competitors")
    return (
        f"https://www.marketbeat.com/stocks/{exchange.upper()}/{symbol.upper()}"
        "/competitors-and-alternatives/"
    )


def _press_releases_url(symbol: str, exchange: str | None) -> str:
    """Build the Nasdaq press-releases URL.

    Args:
        symbol:   Equity ticker, e.g. ``'AAPL'``.
        exchange: Unused -- Nasdaq URL is exchange-agnostic.

    Returns:
        Fully qualified Nasdaq press-releases page URL.
    """
    return f"https://www.nasdaq.com/market-activity/stocks/{symbol.lower()}/press-releases"


def _option_chain_url(symbol: str, exchange: str | None) -> str:
    """Build the Nasdaq option-chain URL.

    Args:
        symbol:   Equity ticker, e.g. ``'AAPL'``.
        exchange: Unused -- Nasdaq URL is exchange-agnostic.

    Returns:
        Fully qualified Nasdaq option-chain page URL.
    """
    return f"https://www.nasdaq.com/market-activity/stocks/{symbol.lower()}/option-chain"


def _estimate_url(symbol: str, exchange: str | None) -> str:
    """Build the Nasdaq analyst-estimates URL.

    Args:
        symbol:   Equity ticker, e.g. ``'AAPL'``.
        exchange: Unused -- Nasdaq URL is exchange-agnostic.

    Returns:
        Fully qualified Nasdaq analyst-estimates page URL.
    """
    return f"https://finance.yahoo.com/quote/{symbol.upper()}/analysis/"


#: Maps each :class:`WebPageType` to its URL-builder callable.
URL_BUILDERS: dict[WebPageType, Callable[[str, str | None], str]] = {
    WebPageType.competitors: _competitors_url,
    WebPageType.press_releases: _press_releases_url,
    WebPageType.option_chain: _option_chain_url,
    WebPageType.estimate: _estimate_url,
}


def build_url(page_type: WebPageType, symbol: str, exchange: str | None = None) -> str:
    """Return the canonical URL for the given page type and symbol.

    Args:
        page_type: Category of page to build the URL for.
        symbol:    Equity ticker symbol.
        exchange:  Exchange name; required only for ``competitors``.

    Returns:
        Canonical URL string.

    Raises:
        ValueError: When *exchange* is missing for page types that require it.
        KeyError:   When *page_type* has no registered URL builder (should never
                    happen with a validated :class:`WebPageType`).
    """
    builder = URL_BUILDERS[page_type]
    return builder(symbol, exchange)
