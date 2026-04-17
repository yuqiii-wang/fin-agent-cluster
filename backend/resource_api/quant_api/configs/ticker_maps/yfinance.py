"""yfinance TICKER_MAP — canonical symbol → yfinance symbol.

yfinance handles most exchange-listed instruments natively.
Key overrides:
  - Stooq-native Treasury tickers (^US1MT, ^US6MT) have no direct yfinance
    equivalent; CBOE rate indices (^IRX, ^FVX) are used as proxies.
  - SOFR canonical (SOFR) is not on yfinance; ^IRX (3-month T-bill) is proxy.
  - TOPIX (^TOPX) is not available on yfinance; use datareader/Stooq instead.
  - None means yfinance cannot serve the ticker; client falls through.
"""

TICKER_MAP: dict[str, str | None] = {
    # ── SOFR proxy ─────────────────────────────────────────────────────────
    # Actual SOFR is served by FRED; yfinance uses 3-month T-bill as proxy.
    "SOFR":      "^IRX",   # SOFR overnight proxy (13-week T-bill)
    # ── Treasury yield proxies ─────────────────────────────────────────────
    "^US1MT":    "^IRX",   # 1-month T-bill → 3-month CBOE ^IRX (closest proxy)
    "^US6MT":    "^FVX",   # 6-month T-bill → 5-year note ^FVX (proxy)
    # ── Commodity futures (=F) — yfinance serves all natively ──────────────
    "GC=F":      "GC=F",   # Gold (COMEX)
    "SI=F":      "SI=F",   # Silver (COMEX)
    "CL=F":      "CL=F",   # WTI Crude Oil (NYMEX)
    "NG=F":      "NG=F",   # Natural Gas (Henry Hub)
    "BZ=F":      "BZ=F",   # Brent Crude (ICE)
    "HG=F":      "HG=F",   # Copper (COMEX)
    "ZQ=F":      "ZQ=F",   # 30-day Fed Funds futures
    "SR1=F":     "SR1=F",  # CME 1-month SOFR futures
    # ── CBOE yield indices ─────────────────────────────────────────────────
    "^IRX":      "^IRX",   # 13-week T-bill
    "^TNX":      "^TNX",   # 10-year Treasury
    "^TYX":      "^TYX",   # 30-year Treasury
    "^FVX":      "^FVX",   # 5-year Treasury
    # ── US equity indices ──────────────────────────────────────────────────
    "^GSPC":     "^GSPC",  # S&P 500
    "^IXIC":     "^IXIC",  # NASDAQ Composite
    "^NDX":      "^NDX",   # NASDAQ 100
    "^DJI":      "^DJI",   # Dow Jones Industrial Average
    "^RUT":      "^RUT",   # Russell 2000
    # ── International indices ──────────────────────────────────────────────
    "^N225":     "^N225",  # Nikkei 225
    "^TOPX":     None,     # TOPIX — not on yfinance; use datareader (Stooq)
    "^HSI":      "^HSI",   # Hang Seng
    "^HSCE":     "^HSCE",  # Hang Seng China Enterprises
    "^FTSE":     "^FTSE",  # FTSE 100
    "^GDAXI":    "^GDAXI", # DAX 40
    "^FCHI":     "^FCHI",  # CAC 40
    "^SSMI":     "^SSMI",  # SMI
    "^AXJO":     "^AXJO",  # S&P/ASX 200
    "^AORD":     "^AORD",  # All Ordinaries
    "^KS11":     "^KS11",  # KOSPI
    "^BSESN":    "^BSESN", # BSE Sensex
    "^NSEI":     "^NSEI",  # Nifty 50
    "^STI":      "^STI",   # Straits Times Index
    "^TWII":     "^TWII",  # TAIEX
    "^BVSP":     "^BVSP",  # Ibovespa
    "^IBEX":     "^IBEX",  # IBEX 35
    "^AEX":      "^AEX",   # AEX
    "^GSPTSE":   "^GSPTSE",# S&P/TSX Composite
    "^JKSE":     "^JKSE",  # IDX Composite
    "^MXX":      "^MXX",   # IPC Mexico
    "FTSEMIB.MI":"FTSEMIB.MI",
    "^KQ11":     "^KQ11",  # KOSDAQ
    # ── Chinese A-share indices ────────────────────────────────────────────
    "000001.SS":  "000001.SS",
    "399001.SZ":  "399001.SZ",
    "399006.SZ":  "399006.SZ",
    "000300.SS":  "000300.SS",
    # ── Crypto ─────────────────────────────────────────────────────────────
    "BTC-USD":   "BTC-USD",
    "ETH-USD":   "ETH-USD",
}
