"""Unit tests for the FRED provider.

Tests verify CSV parsing, rate-as-OHLCV construction, and missing-value
skipping without making real network calls.  httpx.Client is mocked.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from backend.resource_api.exceptions import ProviderNotFoundError
from backend.resource_api.quant_api.providers.fred_provider import _fetch_fred_series


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _mock_response(text: str, status_code: int = 200) -> MagicMock:
    """Build a mock httpx Response."""
    resp = MagicMock()
    resp.status_code = status_code
    resp.text = text
    resp.raise_for_status = MagicMock()
    return resp


# ---------------------------------------------------------------------------
# SOFR rate series
# ---------------------------------------------------------------------------

_CSV_SOFR = (
    "DATE,SOFR\n"
    "2024-01-01,.\n"          # missing (New Year's Day)
    "2024-01-02,5.31\n"
    "2024-01-03,5.31\n"
    "2024-01-04,5.31\n"
    "2024-01-05,5.31\n"
)


@patch("backend.resource_api.quant_api.providers.fred_provider.httpx.Client")
def test_fetch_sofr_returns_bars(mock_client_cls: MagicMock) -> None:
    """SOFR CSV is parsed into daily bars; rows with '.' are skipped."""
    mock_resp = _mock_response(_CSV_SOFR)
    mock_client_cls.return_value.__enter__.return_value.get.return_value = mock_resp

    result = _fetch_fred_series("SOFR", "SOFR", {"period": "1mo"})

    assert result.source == "fred"
    # 2024-01-01 is missing ('.'), so 4 valid bars
    assert len(result.bars) == 4
    first = result.bars[0]
    assert first.date == "2024-01-02"
    # Rate bars: open == high == low == close == value
    assert first.open == pytest.approx(5.31)
    assert first.high == pytest.approx(5.31)
    assert first.low == pytest.approx(5.31)
    assert first.close == pytest.approx(5.31)
    assert first.volume == 0


# ---------------------------------------------------------------------------
# 10-Year Treasury yield
# ---------------------------------------------------------------------------

_CSV_DGS10 = (
    "DATE,DGS10\n"
    "2024-01-02,3.97\n"
    "2024-01-03,3.99\n"
    "2024-01-04,4.01\n"
)


@patch("backend.resource_api.quant_api.providers.fred_provider.httpx.Client")
def test_fetch_dgs10_returns_bars(mock_client_cls: MagicMock) -> None:
    """DGS10 series is parsed into daily bars with correct values."""
    mock_resp = _mock_response(_CSV_DGS10)
    mock_client_cls.return_value.__enter__.return_value.get.return_value = mock_resp

    result = _fetch_fred_series("DGS10", "^TNX", {"period": "1mo"})

    assert result.source == "fred"
    assert len(result.bars) == 3
    assert result.bars[0].close == pytest.approx(3.97)
    assert result.bars[2].close == pytest.approx(4.01)


# ---------------------------------------------------------------------------
# Gold (LBMA AM fix)
# ---------------------------------------------------------------------------

_CSV_GOLD_LBMA = (
    "DATE,GOLDAMGBD228NLBM\n"
    "2024-01-02,2063.10\n"
    "2024-01-03,2045.90\n"
    "2024-01-04,2025.80\n"
    "2024-01-05,.\n"           # missing (no LBMA fix on this day)
)


@patch("backend.resource_api.quant_api.providers.fred_provider.httpx.Client")
def test_fetch_gold_lbma_skips_missing(mock_client_cls: MagicMock) -> None:
    """LBMA gold series: rows with '.' are skipped; remaining parsed correctly."""
    mock_resp = _mock_response(_CSV_GOLD_LBMA)
    mock_client_cls.return_value.__enter__.return_value.get.return_value = mock_resp

    result = _fetch_fred_series("GOLDAMGBD228NLBM", "GC=F", {"period": "1mo"})

    assert len(result.bars) == 3
    assert result.bars[0].open == pytest.approx(2063.10)
    assert result.bars[1].close == pytest.approx(2045.90)


# ---------------------------------------------------------------------------
# Error conditions
# ---------------------------------------------------------------------------

@patch("backend.resource_api.quant_api.providers.fred_provider.httpx.Client")
def test_fetch_empty_csv_raises(mock_client_cls: MagicMock) -> None:
    """An empty response raises ProviderNotFoundError."""
    mock_resp = _mock_response("DATE,SOFR\n")
    mock_client_cls.return_value.__enter__.return_value.get.return_value = mock_resp

    with pytest.raises(ProviderNotFoundError):
        _fetch_fred_series("SOFR", "SOFR", {"period": "1mo"})


@patch("backend.resource_api.quant_api.providers.fred_provider.httpx.Client")
def test_fetch_all_missing_rows_raises(mock_client_cls: MagicMock) -> None:
    """All-missing CSV rows (all '.') raises ProviderNotFoundError."""
    csv_all_missing = "DATE,SOFR\n2024-01-01,.\n2024-01-06,.\n"
    mock_resp = _mock_response(csv_all_missing)
    mock_client_cls.return_value.__enter__.return_value.get.return_value = mock_resp

    with pytest.raises(ProviderNotFoundError):
        _fetch_fred_series("SOFR", "SOFR", {"period": "1mo"})


@patch("backend.resource_api.quant_api.providers.fred_provider.httpx.Client")
def test_fetch_html_response_raises(mock_client_cls: MagicMock) -> None:
    """HTML error page raises ProviderNotFoundError."""
    mock_resp = _mock_response("<html><body>error</body></html>")
    mock_client_cls.return_value.__enter__.return_value.get.return_value = mock_resp

    with pytest.raises(ProviderNotFoundError):
        _fetch_fred_series("UNKNOWN", "UNKNOWN", {"period": "1mo"})


# ---------------------------------------------------------------------------
# Bars are sorted ascending by date
# ---------------------------------------------------------------------------

@patch("backend.resource_api.quant_api.providers.fred_provider.httpx.Client")
def test_fetch_bars_sorted_ascending(mock_client_cls: MagicMock) -> None:
    """Bars returned in ascending date order even if CSV is out-of-order."""
    csv_unsorted = (
        "DATE,DGS10\n"
        "2024-01-05,4.10\n"
        "2024-01-02,3.97\n"
        "2024-01-03,3.99\n"
    )
    mock_resp = _mock_response(csv_unsorted)
    mock_client_cls.return_value.__enter__.return_value.get.return_value = mock_resp

    result = _fetch_fred_series("DGS10", "^TNX", {"period": "1mo"})

    dates = [b.date for b in result.bars]
    assert dates == sorted(dates)
