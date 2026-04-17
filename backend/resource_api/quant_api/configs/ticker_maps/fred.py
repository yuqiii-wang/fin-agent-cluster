"""FRED TICKER_MAP — canonical symbol → FRED series ID.

FRED (Federal Reserve Economic Data, St. Louis Fed) is the authoritative free
source for US interest-rate and money-market series.  The FRED CSV endpoint
requires no API key:
  https://fred.stlouisfed.org/graph/fredgraph.csv?id={SERIES_ID}

Key series used here:
  SOFR         — NY FRB Secured Overnight Financing Rate (daily, since Apr 2018)
  DGS*         — Treasury constant-maturity yields (daily)
  DTB3         — 3-month T-bill secondary-market discount rate (≈ ^IRX proxy)
  GOLDAMGBD228NLBM — LBMA Gold Price AM, USD/troy oz (daily)

Equities, crypto, futures, and anything else not published by FRED map to None.
"""

TICKER_MAP: dict[str, str | None] = {
    # ── SOFR overnight rate (actual NY FRB publication, T+1 lag) ──────────
    "SOFR":      "SOFR",
    # ── US Treasury constant-maturity yields ──────────────────────────────
    "^US1MT":    "DGS1MO",   # 1-month constant maturity
    "^US3MT":    "DGS3MO",   # 3-month constant maturity
    "^US6MT":    "DGS6MO",   # 6-month constant maturity
    "^IRX":      "DTB3",     # 13-week T-bill discount rate (closest to CBOE ^IRX)
    "^FVX":      "DGS5",     # 5-year constant maturity
    "^TNX":      "DGS10",    # 10-year constant maturity
    "^TYX":      "DGS30",    # 30-year constant maturity
    # ── Gold — LBMA Gold Price AM (USD/troy oz, daily fix) ────────────────
    # Note: FRED LBMA data vs COMEX futures (GC.F/GC=F) differ slightly;
    # LBMA fix is a spot reference, not settlement price.
    "GC=F":      "GOLDAMGBD228NLBM",
    # ── Silver — FRED does not publish a reliable daily silver spot series ─
    "SI=F":      None,
    # ── All other instruments — equities, indices, futures, crypto ────────
    "CL=F":      None,
    "NG=F":      None,
    "BZ=F":      None,
    "HG=F":      None,
    "ZQ=F":      None,
    "SR1=F":     None,
    "BTC-USD":   None,
    "ETH-USD":   None,
    "^GSPC":     None,
    "^IXIC":     None,
    "^NDX":      None,
    "^DJI":      None,
    "^RUT":      None,
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
    "000001.SS": None,
    "399001.SZ": None,
    "399006.SZ": None,
    "000300.SS": None,
}
