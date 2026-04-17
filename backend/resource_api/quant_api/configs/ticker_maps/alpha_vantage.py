"""Alpha Vantage TICKER_MAP — canonical symbol → Alpha Vantage symbol.

Alpha Vantage TIME_SERIES_* endpoints are designed for equities.
Commodity futures (=F), CBOE yield indices, Treasury synthetics, market-cap
indices, crypto (separate AV endpoint), and rate series are not supported via
the standard OHLCV endpoints.  Mapping to None causes the client to skip AV
and try the next provider, avoiding wasted API quota calls.

Chinese A-share tickers use AV's .SHH / .SHZ exchange suffixes.
"""

TICKER_MAP: dict[str, str | None] = {
    # ── SOFR / rate series — not in AV equity endpoints ───────────────────
    "SOFR":      None,
    # ── Commodity futures — not available in TIME_SERIES_DAILY ────────────
    "GC=F":      None,
    "SI=F":      None,
    "CL=F":      None,
    "NG=F":      None,
    "BZ=F":      None,
    "HG=F":      None,
    "ZQ=F":      None,
    "SR1=F":     None,
    # ── Treasury / CBOE yield indices — not in AV equity endpoints ────────
    "^IRX":      None,
    "^TNX":      None,
    "^TYX":      None,
    "^FVX":      None,
    "^US1MT":    None,
    "^US6MT":    None,
    # ── US equity indices — AV does not support index OHLCV ───────────────
    "^GSPC":     None,
    "^IXIC":     None,
    "^NDX":      None,
    "^DJI":      None,
    "^RUT":      None,
    # ── International indices — not supported ─────────────────────────────
    "^N225":     None,
    "^TOPX":     None,
    "^HSI":      None,
    "^HSCE":     None,
    "^FTSE":     None,
    "^GDAXI":    None,
    "^FCHI":     None,
    "^SSMI":     None,
    "^AXJO":     None,
    "^AORD":     None,
    "^KS11":     None,
    "^KQ11":     None,
    "^BSESN":    None,
    "^NSEI":     None,
    "^STI":      None,
    "^TWII":     None,
    "^BVSP":     None,
    "^IBEX":     None,
    "^AEX":      None,
    "^GSPTSE":   None,
    "^MXX":      None,
    "^JKSE":     None,
    "FTSEMIB.MI": None,
    # ── Chinese A-share indices — use AV .SHH / .SHZ exchange suffixes ────
    "000001.SS":  "000001.SHH",
    "399001.SZ":  "399001.SHZ",
    "399006.SZ":  "399006.SHZ",
    "000300.SS":  "000300.SHH",
    # ── Crypto — AV has a separate DIGITAL_CURRENCY endpoint; skip equity ─
    "BTC-USD":   None,
    "ETH-USD":   None,
}
