"""Unit tests for the FMP (Financial Modeling Prep) provider.

Tests verify JSON parsing, OHLCV bar construction, quote extraction, and
error handling without making real network calls.  httpx.AsyncClient is mocked.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from backend.resource_api.exceptions import ProviderNotFoundError
from backend.resource_api.quant_api.providers.fmp_provider import (
    _fetch_daily_ohlcv,
    _fetch_quote,
    _fetch_overview,
    fetch,
)
from backend.resource_api.quant_api.models import QuantQuery

_BASE_URL = "https://financialmodelingprep.com/stable"
_API_KEY = "test_key"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _mock_response(json_data: object, status_code: int = 200) -> MagicMock:
    """Build a mock httpx Response returning json_data."""
    resp = MagicMock()
    resp.status_code = status_code
    resp.json = MagicMock(return_value=json_data)
    resp.raise_for_status = MagicMock()
    return resp


def _patch_get(json_data: object, status_code: int = 200):
    """Context manager: patch httpx.AsyncClient.get to return json_data."""
    mock_resp = _mock_response(json_data, status_code)
    mock_client = AsyncMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)
    mock_client.get = AsyncMock(return_value=mock_resp)
    return patch(
        "backend.resource_api.quant_api.providers.fmp_provider.httpx.AsyncClient",
        return_value=mock_client,
    )


# ---------------------------------------------------------------------------
# Daily OHLCV
# ---------------------------------------------------------------------------

_HISTORICAL_AAPL = {
    "symbol": "AAPL",
    "historical": [
        {"date": "2024-01-02", "open": 185.0, "high": 188.0, "low": 184.0, "close": 187.0, "volume": 50000000, "adjClose": 187.0},
        {"date": "2024-01-03", "open": 187.0, "high": 190.0, "low": 186.0, "close": 189.0, "volume": 48000000, "adjClose": 189.0},
        {"date": "2024-01-04", "open": 189.0, "high": 191.0, "low": 188.0, "close": 190.0, "volume": 45000000, "adjClose": 190.0},
    ],
}


@pytest.mark.asyncio
async def test_fetch_daily_ohlcv_returns_bars() -> None:
    """Daily OHLCV bars are correctly parsed from FMP historical response."""
    with _patch_get(_HISTORICAL_AAPL):
        result = await _fetch_daily_ohlcv("AAPL", {"period": "1mo"}, _BASE_URL, _API_KEY)

    assert result.source == "fmp"
    assert result.method == "daily_ohlcv"
    assert len(result.bars) == 3
    assert result.bars[0].date == "2024-01-02"
    assert result.bars[0].open == pytest.approx(185.0)
    assert result.bars[0].close == pytest.approx(187.0)
    assert result.bars[0].volume == 50000000
    assert result.bars[0].adj_close == pytest.approx(187.0)


@pytest.mark.asyncio
async def test_fetch_daily_ohlcv_sorted_ascending() -> None:
    """Bars are returned in ascending date order regardless of API order."""
    # Reverse the historical list to simulate descending API response
    reversed_data = {
        "symbol": "AAPL",
        "historical": list(reversed(_HISTORICAL_AAPL["historical"])),
    }
    with _patch_get(reversed_data):
        result = await _fetch_daily_ohlcv("AAPL", {"period": "1mo"}, _BASE_URL, _API_KEY)

    assert result.bars[0].date == "2024-01-02"
    assert result.bars[-1].date == "2024-01-04"


@pytest.mark.asyncio
async def test_fetch_daily_ohlcv_empty_raises() -> None:
    """Empty historical list raises ProviderNotFoundError."""
    with _patch_get({"symbol": "UNKNOWN", "historical": []}):
        with pytest.raises(ProviderNotFoundError):
            await _fetch_daily_ohlcv("UNKNOWN", {}, _BASE_URL, _API_KEY)


@pytest.mark.asyncio
async def test_fetch_daily_ohlcv_error_message_raises() -> None:
    """FMP error JSON payload raises ProviderNotFoundError."""
    with _patch_get({"Error Message": "Invalid API Key"}):
        with pytest.raises(ProviderNotFoundError, match="Invalid API Key"):
            await _fetch_daily_ohlcv("AAPL", {}, _BASE_URL, _API_KEY)


@pytest.mark.asyncio
async def test_fetch_daily_ohlcv_404_raises() -> None:
    """HTTP 404 raises ProviderNotFoundError."""
    with _patch_get({}, status_code=404):
        with pytest.raises(ProviderNotFoundError):
            await _fetch_daily_ohlcv("AAPL", {}, _BASE_URL, _API_KEY)


# ---------------------------------------------------------------------------
# Quote
# ---------------------------------------------------------------------------

_QUOTE_AAPL = [
    {
        "symbol": "AAPL",
        "price": 190.5,
        "change": 2.5,
        "changesPercentage": 1.33,
        "volume": 52000000,
        "marketCap": 2950000000000,
    }
]


@pytest.mark.asyncio
async def test_fetch_quote_returns_price() -> None:
    """Quote is extracted from the first element of the FMP quote array."""
    with _patch_get(_QUOTE_AAPL):
        result = await _fetch_quote("AAPL", _BASE_URL, _API_KEY)

    assert result.source == "fmp"
    assert result.method == "quote"
    assert result.quote is not None
    assert result.quote.price == pytest.approx(190.5)
    assert result.quote.change == pytest.approx(2.5)
    assert result.quote.change_pct == pytest.approx(1.33)
    assert result.quote.volume == 52000000
    assert result.quote.market_cap == pytest.approx(2950000000000)


@pytest.mark.asyncio
async def test_fetch_quote_empty_raises() -> None:
    """Empty quote array raises ProviderNotFoundError."""
    with _patch_get([]):
        with pytest.raises(ProviderNotFoundError):
            await _fetch_quote("UNKNOWN", _BASE_URL, _API_KEY)


@pytest.mark.asyncio
async def test_fetch_quote_zero_price_raises() -> None:
    """A quote with price=0 raises ProviderNotFoundError."""
    with _patch_get([{"symbol": "AAPL", "price": 0, "change": None, "changesPercentage": None, "volume": None, "marketCap": None}]):
        with pytest.raises(ProviderNotFoundError):
            await _fetch_quote("AAPL", _BASE_URL, _API_KEY)


# ---------------------------------------------------------------------------
# Overview (profile)
# ---------------------------------------------------------------------------

_PROFILE_AAPL = [
    {
        "symbol": "AAPL",
        "companyName": "Apple Inc.",
        "exchange": "NASDAQ",
        "industry": "Consumer Electronics",
        "sector": "Technology",
        "mktCap": 2950000000000,
    }
]


@pytest.mark.asyncio
async def test_fetch_overview_returns_dict() -> None:
    """Profile is returned as an overview dict in QuantResult."""
    with _patch_get(_PROFILE_AAPL):
        result = await _fetch_overview("AAPL", _BASE_URL, _API_KEY)

    assert result.source == "fmp"
    assert result.method == "overview"
    assert result.overview is not None
    assert result.overview["companyName"] == "Apple Inc."
    assert result.overview["exchange"] == "NASDAQ"


@pytest.mark.asyncio
async def test_fetch_overview_empty_raises() -> None:
    """Empty profile list raises ProviderNotFoundError."""
    with _patch_get([]):
        with pytest.raises(ProviderNotFoundError):
            await _fetch_overview("UNKNOWN", _BASE_URL, _API_KEY)


# ---------------------------------------------------------------------------
# Intraday — not supported
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_intraday_raises_not_found() -> None:
    """FMP intraday raises ProviderNotFoundError (free tier not supported)."""
    query = QuantQuery(symbol="AAPL", method="intraday_ohlcv", params={"interval": "5m"})
    with pytest.raises(ProviderNotFoundError, match="intraday"):
        await fetch(query, _BASE_URL, _API_KEY)


# ---------------------------------------------------------------------------
# fetch() dispatcher
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_fetch_dispatcher_daily_ohlcv() -> None:
    """fetch() routes daily_ohlcv to _fetch_daily_ohlcv."""
    query = QuantQuery(symbol="AAPL", method="daily_ohlcv", params={"period": "1mo"})
    with _patch_get(_HISTORICAL_AAPL):
        result = await fetch(query, _BASE_URL, _API_KEY)
    assert result.method == "daily_ohlcv"
    assert result.source == "fmp"


@pytest.mark.asyncio
async def test_fetch_dispatcher_quote() -> None:
    """fetch() routes quote to _fetch_quote."""
    query = QuantQuery(symbol="AAPL", method="quote", params={})
    with _patch_get(_QUOTE_AAPL):
        result = await fetch(query, _BASE_URL, _API_KEY)
    assert result.method == "quote"
    assert result.source == "fmp"


@pytest.mark.asyncio
async def test_fetch_dispatcher_overview() -> None:
    """fetch() routes overview to _fetch_overview."""
    query = QuantQuery(symbol="AAPL", method="overview", params={})
    with _patch_get(_PROFILE_AAPL):
        result = await fetch(query, _BASE_URL, _API_KEY)
    assert result.method == "overview"
    assert result.source == "fmp"
