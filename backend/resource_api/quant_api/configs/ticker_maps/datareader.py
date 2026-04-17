"""datareader (Stooq) TICKER_MAP — canonical symbol → Stooq symbol.

Stooq uses different symbol conventions from yfinance:
  - Commodity futures: GC=F → GC.F
  - US equity indices: some are restricted on Stooq's free tier (mapped None)
  - Treasury yields:   Stooq does not reliably serve yield data (all None)
  - Rate series (SOFR): not on Stooq (None)
  - Crypto: not on Stooq (None)

A None value means Stooq cannot serve the ticker; client falls through to
the next provider in the chain (typically FRED or yfinance).

Note: NG=F (Natural Gas) maps to None because Stooq only carries specific
dated contract months, not a generic front-month contract.
"""

TICKER_MAP: dict[str, str | None] = {
    # ── SOFR / rate series — not on Stooq ─────────────────────────────────
    "SOFR":      None,
    # ── Commodity futures: =F suffix → .F suffix ──────────────────────────
    "GC=F":      "GC.F",    # Gold (COMEX)
    "SI=F":      "SI.F",    # Silver (COMEX)
    "CL=F":      None,       # WTI Crude Oil — Stooq does not reliably serve it
    "NG=F":      None,       # Natural Gas — no Stooq generic front-month
    "BZ=F":      "BZ.F",    # Brent Crude (ICE)
    "HG=F":      "HG.F",    # Copper (COMEX)
    "ZQ=F":      None,       # 30-day Fed Funds futures — not on Stooq
    "SR1=F":     None,       # CME 1-month SOFR futures — not on Stooq
    # ── Treasury yields — Stooq does not reliably serve yield indices ──────
    "^US1MT":    None,       # 1-month T-bill yield
    "^US6MT":    None,       # 6-month T-bill yield
    "^TNX":      None,       # 10-year Treasury
    "^IRX":      None,       # 3-month T-bill
    "^FVX":      None,       # 5-year Treasury
    "^TYX":      None,       # 30-year Treasury
    # ── US equity indices — major indices restricted on Stooq free tier ────
    "^GSPC":     None,       # S&P 500
    "^IXIC":     None,       # NASDAQ Composite
    "^NDX":      "^NDX",     # NASDAQ 100
    "^DJI":      None,       # Dow Jones
    "^RUT":      "^RUT",     # Russell 2000
    # ── International equity indices ──────────────────────────────────────
    "^N225":     "^NKX",     # Nikkei 225
    "^TOPX":     "^TPX",     # TOPIX
    "^HSI":      "^HSI",     # Hang Seng
    "^FTSE":     "^FTSE",    # FTSE 100
    "^GDAXI":    "^DAX",     # DAX 40
    "^FCHI":     "^CAC",     # CAC 40
    "^SSMI":     "^SMI",     # SMI
    "^AXJO":     "^AXJO",    # S&P/ASX 200
    "^KS11":     "^KS11",    # KOSPI
    "^BSESN":    "^SENSEX",  # BSE Sensex
    "^NSEI":     "^NIFTY",   # Nifty 50
    "^STI":      "^STI",     # Straits Times
    "^TWII":     "^TWII",    # TAIEX
    "^BVSP":     "^BVSP",    # Ibovespa
    "^IBEX":     "^IBEX",    # IBEX 35
    "^AEX":      "^AEX",     # AEX
    "^GSPTSE":   "^GSPTSE",  # S&P/TSX Composite
    "^MXX":      "^MXX",     # IPC Mexico
    "^JKSE":     "^JKSE",    # IDX Composite (may be unavailable)
    # ── Chinese A-share indices — Stooq uses .CN suffix ───────────────────
    "000001.SS":  "000001.CN",
    "399001.SZ":  "399001.SZ",
    "399006.SZ":  "399006.SZ",
    "000300.SS":  "000300.CN",
    # ── FTSE MIB ──────────────────────────────────────────────────────────
    "FTSEMIB.MI": None,
    # ── Crypto — not on Stooq ─────────────────────────────────────────────
    "BTC-USD":   None,
    "ETH-USD":   None,
}
