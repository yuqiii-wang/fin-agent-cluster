"""Unit tests for translate_symbol and the QUANT_SOURCE_DEFAULTS macro chain."""

import pytest

from backend.resource_api.quant_api.configs.sources import QUANT_SOURCE_DEFAULTS
from backend.resource_api.quant_api.client import translate_symbol


# ---------------------------------------------------------------------------
# translate_symbol
# ---------------------------------------------------------------------------

def test_translate_gold_datareader() -> None:
    assert translate_symbol("GC=F", "datareader") == "GC.F"


def test_translate_silver_datareader() -> None:
    assert translate_symbol("SI=F", "datareader") == "SI.F"


def test_translate_crude_oil_datareader_returns_none() -> None:
    """CL=F is not supported by datareader; translate_symbol returns None."""
    assert translate_symbol("CL=F", "datareader") is None


def test_translate_sofr_fred() -> None:
    assert translate_symbol("SOFR", "fred") == "SOFR"


def test_translate_tnx_fred() -> None:
    assert translate_symbol("^TNX", "fred") == "DGS10"


def test_translate_sofr_yfinance_proxy() -> None:
    """yfinance uses ^IRX as proxy for SOFR."""
    assert translate_symbol("SOFR", "yfinance") == "^IRX"


def test_translate_pass_through_for_unlisted() -> None:
    """A symbol not in any map is returned unchanged (pass-through)."""
    assert translate_symbol("AAPL", "yfinance") == "AAPL"
    assert translate_symbol("AAPL", "datareader") == "AAPL"


def test_translate_bitcoin_fred_returns_none() -> None:
    assert translate_symbol("BTC-USD", "fred") is None


def test_translate_bitcoin_yfinance_passthrough() -> None:
    assert translate_symbol("BTC-USD", "yfinance") == "BTC-USD"


# ---------------------------------------------------------------------------
# QUANT_SOURCE_DEFAULTS macro chain
# ---------------------------------------------------------------------------

def test_macro_chain_starts_with_datareader() -> None:
    """datareader (Stooq) must be first in the macro chain for metals/oil."""
    chain = QUANT_SOURCE_DEFAULTS["macro"]
    assert chain[0] == "datareader"


def test_macro_chain_contains_fred() -> None:
    """fred must appear in the macro chain for SOFR and Treasury yields."""
    chain = QUANT_SOURCE_DEFAULTS["macro"]
    assert "fred" in chain


def test_macro_chain_yfinance_is_last() -> None:
    """yfinance must be last resort in the macro chain."""
    chain = QUANT_SOURCE_DEFAULTS["macro"]
    assert chain[-1] == "yfinance"


def test_default_chain_does_not_need_fred() -> None:
    """The default chain is for equities and does not require fred."""
    chain = QUANT_SOURCE_DEFAULTS["default"]
    # fred is optional for equity chains; yfinance is always last
    assert chain[-1] == "yfinance"
