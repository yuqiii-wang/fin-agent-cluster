"""FMP (Financial Modeling Prep) TICKER_MAP — canonical symbol → FMP symbol.

FMP stable API (https://financialmodelingprep.com/stable) covers:
  - US equities (NYSE, NASDAQ, AMEX) — plain symbol, pass-through
  - Major US/global indices — pass-through (^GSPC, ^IXIC, ^DJI, etc.)
  - Crypto — pass-through (BTC-USD, ETH-USD)

Not supported by FMP:
  - Commodity futures with =F suffix (GC=F, SI=F, CL=F, etc.)
  - Rate/yield series (SOFR, ^US1MT, ^US6MT, ^IRX, ^FVX, ^TNX, ^TYX)
  - Chinese A-share exchange-specific symbols (000001.SS, etc.)

A None value causes the client to skip FMP and try the next provider in the
fallback chain.  Symbols absent from the map are passed through unchanged.
"""

TICKER_MAP: dict[str, str | None] = {
    # ── Commodity futures — not available on FMP ───────────────────────────
    "GC=F":       None,
    "SI=F":       None,
    "CL=F":       None,
    "NG=F":       None,
    "BZ=F":       None,
    "HG=F":       None,
    "ZQ=F":       None,
    "SR1=F":      None,
    # ── Rate / Treasury series — not on FMP ───────────────────────────────
    "SOFR":       None,
    "^US1MT":     None,
    "^US3MT":     None,
    "^US6MT":     None,
    "^IRX":       None,
    "^FVX":       None,
    "^TNX":       None,
    "^TYX":       None,
    # ── Chinese A-shares — not on FMP ─────────────────────────────────────
    "000001.SS":  None,
    "399001.SZ":  None,
    "399006.SZ":  None,
    "000300.SS":  None,
    # ── US equity indices — FMP accepts these pass-through ─────────────────
    "^GSPC":      "^GSPC",
    "^IXIC":      "^IXIC",
    "^NDX":       "^NDX",
    "^DJI":       "^DJI",
    "^RUT":       "^RUT",
    # ── Crypto — FMP accepts pass-through ─────────────────────────────────
    "BTC-USD":    "BTC-USD",
    "ETH-USD":    "ETH-USD",
}
