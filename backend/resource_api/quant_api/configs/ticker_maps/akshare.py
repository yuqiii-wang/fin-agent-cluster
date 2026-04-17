"""AKShare TICKER_MAP — canonical symbol → AKShare symbol.

AKShare is China-centric (A-share indices and equities).
All international tickers, commodities, crypto, and rate series are mapped to
None so the client falls through to datareader or yfinance.

Symbol conventions used by AKShare:
  - A-share stock:  '600519'  (6-digit code — suffix stripped)
  - A-share index:  '000001'  (bare code without .SS / .SZ)
"""

TICKER_MAP: dict[str, str | None] = {
    # ── Chinese A-share indices — strip exchange suffix to bare 6-digit code ─
    "000001.SS":  "000001",   # Shanghai Composite (SSE)
    "399001.SZ":  "399001",   # Shenzhen Component (SZSE)
    "399006.SZ":  "399006",   # ChiNext (SZSE)
    "000300.SS":  "000300",   # CSI 300
    "^SSEC":      "000001",   # Alternative canonical for Shanghai Composite
    # ── HK — limited AKShare support; prefer datareader/yfinance ──────────
    "^HSI":       None,
    "^HSCE":      None,
    # ── SOFR / rate series — not in AKShare ───────────────────────────────
    "SOFR":       None,
    # ── Commodity futures — not in AKShare ────────────────────────────────
    "GC=F":       None,
    "SI=F":       None,
    "CL=F":       None,
    "NG=F":       None,
    "BZ=F":       None,
    "HG=F":       None,
    "ZQ=F":       None,
    "SR1=F":      None,
    # ── Treasury / CBOE yield indices — not in AKShare ────────────────────
    "^IRX":       None,
    "^TNX":       None,
    "^TYX":       None,
    "^FVX":       None,
    "^US1MT":     None,
    "^US6MT":     None,
    # ── US equity indices — not in AKShare ────────────────────────────────
    "^GSPC":      None,
    "^IXIC":      None,
    "^NDX":       None,
    "^DJI":       None,
    "^RUT":       None,
    # ── International indices — not in AKShare ────────────────────────────
    "^N225":      None,
    "^TOPX":      None,
    "^FTSE":      None,
    "^GDAXI":     None,
    "^FCHI":      None,
    "^SSMI":      None,
    "^AXJO":      None,
    "^AORD":      None,
    "^KS11":      None,
    "^KQ11":      None,
    "^BSESN":     None,
    "^NSEI":      None,
    "^STI":       None,
    "^TWII":      None,
    "^BVSP":      None,
    "^IBEX":      None,
    "^AEX":       None,
    "^GSPTSE":    None,
    "^MXX":       None,
    "^JKSE":      None,
    "FTSEMIB.MI": None,
    # ── Crypto — not in AKShare ───────────────────────────────────────────
    "BTC-USD":    None,
    "ETH-USD":    None,
}
