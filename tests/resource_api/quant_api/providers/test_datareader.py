"""Unit tests for the datareader (Stooq) provider.

Tests verify CSV parsing logic and OHLCVBar construction without making real
network calls.  httpx.Client is mocked to return canned CSV responses.
"""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest

from backend.resource_api.exceptions import ProviderNotFoundError
from backend.resource_api.quant_api.providers.datareader_provider import (
    _fetch_stooq_ohlcv,
    _build_stooq_candidates,
)


# ---------------------------------------------------------------------------
# Stooq candidate-building rules
# ---------------------------------------------------------------------------

def test_build_candidates_futures_suffix() -> None:
    """=F futures are already translated to .F; candidate list includes bare code."""
    candidates = _build_stooq_candidates("GC.F")
    assert "GC.F" in candidates
    assert "GC" in candidates  # bare code fallback


def test_build_candidates_caret_index() -> None:
    """^-prefixed index: bare variant without ^ should be included."""
    candidates = _build_stooq_candidates("^NDX")
    assert "^NDX" in candidates
    assert "NDX" in candidates


def test_build_candidates_plain_equity() -> None:
    """Plain US equity: .US suffix candidate should be appended."""
    candidates = _build_stooq_candidates("AAPL")
    assert "AAPL" in candidates
    assert "AAPL.US" in candidates


# ---------------------------------------------------------------------------
# CSV parsing — successful response
# ---------------------------------------------------------------------------

_CSV_GOLD = (
    "Date,Open,High,Low,Close,Volume\r\n"
    "2024-01-02,2063.50,2089.70,2054.30,2063.20,145000\r\n"
    "2024-01-03,2063.20,2071.00,2045.60,2058.40,132000\r\n"
    "2024-01-04,2058.40,2060.00,2019.20,2025.80,156000\r\n"
)


def _mock_response(text: str, status_code: int = 200) -> MagicMock:
    """Build a mock httpx Response."""
    resp = MagicMock()
    resp.status_code = status_code
    resp.text = text
    resp.raise_for_status = MagicMock()
    return resp


@patch("backend.resource_api.quant_api.providers.datareader_provider.httpx.Client")
def test_fetch_stooq_gold_returns_bars(mock_client_cls: MagicMock) -> None:
    """Successful Stooq CSV for gold returns correctly parsed OHLCVBars."""
    mock_resp = _mock_response(_CSV_GOLD)
    mock_client_cls.return_value.__enter__.return_value.get.return_value = mock_resp

    result = _fetch_stooq_ohlcv("GC.F", {"period": "1mo"})

    assert result.source == "datareader"
    assert result.symbol == "GC.F"
    assert len(result.bars) == 3
    first = result.bars[0]
    assert first.date == "2024-01-02"
    assert first.open == pytest.approx(2063.50)
    assert first.close == pytest.approx(2063.20)
    assert first.volume == 145000


@patch("backend.resource_api.quant_api.providers.datareader_provider.httpx.Client")
def test_fetch_stooq_silver_returns_bars(mock_client_cls: MagicMock) -> None:
    """Successful Stooq CSV for silver (SI.F) returns correctly parsed OHLCVBars."""
    csv_silver = (
        "Date,Open,High,Low,Close,Volume\r\n"
        "2024-01-02,23.15,23.54,23.00,23.45,85000\r\n"
        "2024-01-03,23.45,23.67,23.10,23.30,79000\r\n"
    )
    mock_resp = _mock_response(csv_silver)
    mock_client_cls.return_value.__enter__.return_value.get.return_value = mock_resp

    result = _fetch_stooq_ohlcv("SI.F", {"period": "1mo"})

    assert result.source == "datareader"
    assert len(result.bars) == 2
    assert result.bars[0].close == pytest.approx(23.45)


@patch("backend.resource_api.quant_api.providers.datareader_provider.httpx.Client")
def test_fetch_stooq_empty_csv_raises(mock_client_cls: MagicMock) -> None:
    """Empty CSV response raises ProviderNotFoundError."""
    mock_resp = _mock_response("")
    mock_client_cls.return_value.__enter__.return_value.get.return_value = mock_resp

    with pytest.raises(ProviderNotFoundError):
        _fetch_stooq_ohlcv("CL.F", {"period": "1mo"})


@patch("backend.resource_api.quant_api.providers.datareader_provider.httpx.Client")
def test_fetch_stooq_html_response_raises(mock_client_cls: MagicMock) -> None:
    """HTML response (redirect / error page) raises ProviderNotFoundError."""
    mock_resp = _mock_response("<html><body>Not found</body></html>")
    mock_client_cls.return_value.__enter__.return_value.get.return_value = mock_resp

    with pytest.raises(ProviderNotFoundError):
        _fetch_stooq_ohlcv("UNKNOWN.F", {"period": "1mo"})


@patch("backend.resource_api.quant_api.providers.datareader_provider.httpx.Client")
def test_fetch_stooq_bars_sorted_ascending(mock_client_cls: MagicMock) -> None:
    """Returned bars are sorted by date ascending regardless of CSV order."""
    csv_reversed = (
        "Date,Open,High,Low,Close,Volume\r\n"
        "2024-01-04,2025.80,2030.00,2010.00,2028.00,110000\r\n"
        "2024-01-02,2063.50,2089.70,2054.30,2063.20,145000\r\n"
        "2024-01-03,2063.20,2071.00,2045.60,2058.40,132000\r\n"
    )
    mock_resp = _mock_response(csv_reversed)
    mock_client_cls.return_value.__enter__.return_value.get.return_value = mock_resp

    result = _fetch_stooq_ohlcv("GC.F", {"period": "1mo"})

    dates = [b.date for b in result.bars]
    assert dates == sorted(dates)
