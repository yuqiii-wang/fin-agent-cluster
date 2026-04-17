"""Unit tests: verify which tickers are supported by which providers.

Each test asserts the expected TICKER_MAP entry (supported / unsupported / proxy)
for each canonical symbol found in MACRO_SYMBOLS and BOND_TENORS.  No network
calls are made — these tests are pure config validation.

Coverage matrix (provider rows × ticker columns):

             | GC=F | SI=F | CL=F | NG=F | SOFR | ^TNX | ^US1MT | BTC-USD | ^GSPC | AAPL  |
datareader   |  .F  |  .F  | None | None | None | None |  None  |  None   | None  |  n/a  |
fred         | LBMA | None | None | None | SOFR | DGS10| DGS1MO |  None   | None  |  n/a  |
alpha_vantage| None | None | None | None | None | None |  None  |  None   | None  | AAPL  |
akshare      | None | None | None | None | None | None |  None  |  None   | None  |  n/a  |
yfinance     | GC=F | SI=F | CL=F | NG=F | ^IRX | ^TNX |  ^IRX  | BTC-USD | ^GSPC |  n/a  |
fmp          | None | None | None | None | None | None |  None  | BTC-USD | ^GSPC | AAPL  |
"""

import pytest

from backend.resource_api.quant_api.configs.macro_symbols import MACRO_SYMBOLS, BOND_TENORS
from backend.resource_api.quant_api.configs.ticker_maps import (
    datareader,
    alpha_vantage,
    akshare,
    yfinance,
    fred,
    fmp,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def supported(ticker_map: dict, symbol: str) -> bool:
    """Return True when the symbol is explicitly mapped to a non-None value."""
    return ticker_map.get(symbol) is not None


def not_supported(ticker_map: dict, symbol: str) -> bool:
    """Return True when the symbol is explicitly mapped to None."""
    return ticker_map.get(symbol) is None and symbol in ticker_map


def maps_to(ticker_map: dict, symbol: str, expected: str) -> bool:
    """Return True when symbol maps to exactly expected."""
    return ticker_map.get(symbol) == expected


# ---------------------------------------------------------------------------
# MACRO_SYMBOLS completeness check
# ---------------------------------------------------------------------------

def test_macro_symbols_contains_silver() -> None:
    """silver must be present in MACRO_SYMBOLS after the refactor."""
    assert "silver" in MACRO_SYMBOLS
    symbol, label = MACRO_SYMBOLS["silver"]
    assert symbol == "SI=F"
    assert "Silver" in label


def test_macro_symbols_sofr_uses_actual_fred_canonical() -> None:
    """sofr_on must use the canonical 'SOFR' ticker (actual FRED series) not ^IRX proxy."""
    assert "sofr_on" in MACRO_SYMBOLS
    symbol, _label = MACRO_SYMBOLS["sofr_on"]
    assert symbol == "SOFR", f"Expected 'SOFR' but got '{symbol}'"


def test_macro_symbols_has_expected_keys() -> None:
    """All expected macro keys are present."""
    expected = {"gold", "silver", "crude_oil", "natural_gas", "sofr_on", "sofr_tn", "sofr_1m", "bitcoin"}
    assert expected == set(MACRO_SYMBOLS.keys())


def test_bond_tenors_has_expected_symbols() -> None:
    """All four bond tenor canonical symbols are present."""
    symbols = {s for s, _ in BOND_TENORS}
    assert "^US1MT" in symbols
    assert "^US6MT" in symbols
    assert "^FVX" in symbols
    assert "^TNX" in symbols


# ---------------------------------------------------------------------------
# Gold (GC=F) — preferred: datareader (Stooq GC.F), then FRED, then yfinance
# ---------------------------------------------------------------------------

def test_gold_datareader_maps_to_stooq() -> None:
    assert maps_to(datareader.TICKER_MAP, "GC=F", "GC.F")


def test_gold_fred_maps_to_lbma() -> None:
    assert maps_to(fred.TICKER_MAP, "GC=F", "GOLDAMGBD228NLBM")


def test_gold_yfinance_maps_to_itself() -> None:
    assert maps_to(yfinance.TICKER_MAP, "GC=F", "GC=F")


def test_gold_alpha_vantage_not_supported() -> None:
    assert not_supported(alpha_vantage.TICKER_MAP, "GC=F")


def test_gold_akshare_not_supported() -> None:
    assert not_supported(akshare.TICKER_MAP, "GC=F")


# ---------------------------------------------------------------------------
# Silver (SI=F) — preferred: datareader (Stooq SI.F), then yfinance (FRED: None)
# ---------------------------------------------------------------------------

def test_silver_datareader_maps_to_stooq() -> None:
    assert maps_to(datareader.TICKER_MAP, "SI=F", "SI.F")


def test_silver_yfinance_maps_to_itself() -> None:
    assert maps_to(yfinance.TICKER_MAP, "SI=F", "SI=F")


def test_silver_fred_not_supported() -> None:
    assert not_supported(fred.TICKER_MAP, "SI=F")


def test_silver_alpha_vantage_not_supported() -> None:
    assert not_supported(alpha_vantage.TICKER_MAP, "SI=F")


def test_silver_akshare_not_supported() -> None:
    assert not_supported(akshare.TICKER_MAP, "SI=F")


# ---------------------------------------------------------------------------
# WTI Crude (CL=F) — yfinance only; datareader and FRED cannot serve it
# ---------------------------------------------------------------------------

def test_crude_oil_datareader_not_supported() -> None:
    assert not_supported(datareader.TICKER_MAP, "CL=F")


def test_crude_oil_fred_not_supported() -> None:
    assert not_supported(fred.TICKER_MAP, "CL=F")


def test_crude_oil_yfinance_maps_to_itself() -> None:
    assert maps_to(yfinance.TICKER_MAP, "CL=F", "CL=F")


# ---------------------------------------------------------------------------
# SOFR — preferred: FRED (actual rate), yfinance fallback (^IRX proxy)
# ---------------------------------------------------------------------------

def test_sofr_fred_maps_to_fred_series() -> None:
    assert maps_to(fred.TICKER_MAP, "SOFR", "SOFR")


def test_sofr_yfinance_maps_to_irx_proxy() -> None:
    """yfinance has no SOFR series; it uses 13-week T-bill ^IRX as proxy."""
    assert maps_to(yfinance.TICKER_MAP, "SOFR", "^IRX")


def test_sofr_datareader_not_supported() -> None:
    assert not_supported(datareader.TICKER_MAP, "SOFR")


def test_sofr_alpha_vantage_not_supported() -> None:
    assert not_supported(alpha_vantage.TICKER_MAP, "SOFR")


def test_sofr_akshare_not_supported() -> None:
    assert not_supported(akshare.TICKER_MAP, "SOFR")


# ---------------------------------------------------------------------------
# 10-Year Treasury (^TNX) — FRED primary, yfinance fallback
# ---------------------------------------------------------------------------

def test_tnx_fred_maps_to_dgs10() -> None:
    assert maps_to(fred.TICKER_MAP, "^TNX", "DGS10")


def test_tnx_yfinance_maps_to_itself() -> None:
    assert maps_to(yfinance.TICKER_MAP, "^TNX", "^TNX")


def test_tnx_datareader_not_supported() -> None:
    assert not_supported(datareader.TICKER_MAP, "^TNX")


# ---------------------------------------------------------------------------
# 1-Month Treasury (^US1MT) — FRED primary; datareader/yfinance proxy
# ---------------------------------------------------------------------------

def test_us1mt_fred_maps_to_dgs1mo() -> None:
    assert maps_to(fred.TICKER_MAP, "^US1MT", "DGS1MO")


def test_us1mt_yfinance_maps_to_irx_proxy() -> None:
    assert maps_to(yfinance.TICKER_MAP, "^US1MT", "^IRX")


def test_us1mt_datareader_not_supported() -> None:
    assert not_supported(datareader.TICKER_MAP, "^US1MT")


# ---------------------------------------------------------------------------
# Bitcoin (BTC-USD) — yfinance only
# ---------------------------------------------------------------------------

def test_bitcoin_yfinance_maps_to_itself() -> None:
    assert maps_to(yfinance.TICKER_MAP, "BTC-USD", "BTC-USD")


def test_bitcoin_datareader_not_supported() -> None:
    assert not_supported(datareader.TICKER_MAP, "BTC-USD")


def test_bitcoin_fred_not_supported() -> None:
    assert not_supported(fred.TICKER_MAP, "BTC-USD")


# ---------------------------------------------------------------------------
# FMP ticker map — US equities / indices pass-through; commodities + rates blocked
# ---------------------------------------------------------------------------

def test_fmp_commodity_futures_not_supported() -> None:
    """All commodity futures must be explicitly blocked in FMP (fall to datareader/yfinance)."""
    for symbol in ("GC=F", "SI=F", "CL=F", "NG=F", "BZ=F", "HG=F", "ZQ=F", "SR1=F"):
        assert not_supported(fmp.TICKER_MAP, symbol), f"Expected FMP to block {symbol}"


def test_fmp_rate_series_not_supported() -> None:
    """SOFR and Treasury yield series must be blocked in FMP (fall to FRED)."""
    for symbol in ("SOFR", "^US1MT", "^US6MT", "^IRX", "^FVX", "^TNX", "^TYX"):
        assert not_supported(fmp.TICKER_MAP, symbol), f"Expected FMP to block {symbol}"


def test_fmp_us_equity_index_passthrough() -> None:
    """Major US indices are passed through to FMP unchanged."""
    for symbol in ("^GSPC", "^IXIC", "^NDX", "^DJI", "^RUT"):
        assert maps_to(fmp.TICKER_MAP, symbol, symbol), f"Expected FMP to pass through {symbol}"


def test_fmp_crypto_passthrough() -> None:
    """Crypto tickers are passed through to FMP unchanged."""
    assert maps_to(fmp.TICKER_MAP, "BTC-USD", "BTC-USD")
    assert maps_to(fmp.TICKER_MAP, "ETH-USD", "ETH-USD")


def test_fmp_us_equity_not_in_map() -> None:
    """Plain US equity tickers (AAPL, MSFT) are absent from FMP map → pass-through."""
    assert "AAPL" not in fmp.TICKER_MAP
    assert "MSFT" not in fmp.TICKER_MAP
    assert "TSLA" not in fmp.TICKER_MAP


def test_fmp_chinese_ashares_not_supported() -> None:
    """Chinese A-share exchange-specific symbols are blocked in FMP."""
    for symbol in ("000001.SS", "399001.SZ", "000300.SS"):
        assert not_supported(fmp.TICKER_MAP, symbol), f"Expected FMP to block {symbol}"


def test_bitcoin_alpha_vantage_not_supported() -> None:
    assert not_supported(alpha_vantage.TICKER_MAP, "BTC-USD")


# ---------------------------------------------------------------------------
# Chinese A-shares — akshare primary
# ---------------------------------------------------------------------------

def test_csi300_akshare_strips_suffix() -> None:
    assert maps_to(akshare.TICKER_MAP, "000300.SS", "000300")


def test_csi300_alpha_vantage_uses_shh_suffix() -> None:
    assert maps_to(alpha_vantage.TICKER_MAP, "000300.SS", "000300.SHH")


def test_csi300_fred_not_supported() -> None:
    assert not_supported(fred.TICKER_MAP, "000300.SS")
