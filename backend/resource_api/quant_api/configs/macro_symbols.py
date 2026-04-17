"""Canonical macro commodity and rate ticker definitions.

Provider coverage notes
-----------------------
Gold  (GC=F):   datareader (Stooq GC.F) → FRED (LBMA AM fix) → yfinance
Silver (SI=F):  datareader (Stooq SI.F) → yfinance
WTI   (CL=F):  yfinance only (Stooq/FRED do not carry generic front-month)
NG    (NG=F):  yfinance only (Stooq does not carry generic front-month)
SOFR  (SOFR):  FRED (actual NY FRB SOFR rate) → yfinance (^IRX proxy)
ZQ=F  :        yfinance only (30-day Fed Funds futures)
SR1=F :        yfinance only (CME 1-month SOFR futures)
BTC   :        yfinance only
"""

MACRO_SYMBOLS: dict[str, tuple[str, str]] = {
    "gold":        ("GC=F",    "Gold ($/oz)"),
    "silver":      ("SI=F",    "Silver ($/oz)"),
    "crude_oil":   ("CL=F",    "WTI Crude Oil ($/bbl)"),
    "natural_gas": ("NG=F",    "Natural Gas ($/MMBtu)"),
    # SOFR canonical ticker: FRED publishes the actual NY FRB overnight SOFR
    # rate daily (T+1).  yfinance falls back to ^IRX (3-month T-bill) as proxy.
    "sofr_on":     ("SOFR",    "SOFR Overnight Rate (%)"),
    "sofr_tn":     ("ZQ=F",    "SOFR Tom/Next (30-day Fed Funds futures proxy, %)"),
    "sofr_1m":     ("SR1=F",   "SOFR 1-Month (CME 1-month SOFR futures, %)"),
    "bitcoin":     ("BTC-USD", "Bitcoin (USD)"),
}

# US Bond yield tickers ordered by tenor (1-month → 6-month → 5-year → 10-year).
# FRED is the preferred provider (DGS* constant-maturity series, daily, free).
# yfinance CBOE indices are fallback: ^FVX and ^TNX.
# ^US1MT and ^US6MT are Stooq symbols; FRED maps them to DGS1MO / DGS6MO.
BOND_TENORS: list[tuple[str, str]] = [
    ("^US1MT", "US Bond 1-Month Yield (%)"),
    ("^US6MT", "US Bond 6-Month Yield (%)"),
    ("^FVX",   "US Bond 5-Year Yield (%)"),
    ("^TNX",   "US Bond 10-Year Yield (%)"),
]
