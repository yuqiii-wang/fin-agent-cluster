"""fetch_macro_ticker / fetch_treasury_yields: macro and treasury data tasks.

Input:  QuantClient, symbol/label/key, thread_id
Output: MacroResult / TreasuryResult
"""

from __future__ import annotations

import logging
from typing import Optional

from backend.graph.agents.market_data.models.quant import MacroResult, OHLCVWindowResult, BondResult
from backend.resource_api.quant_api.client import QuantClient
from backend.resource_api.quant_api.models import QuantQuery, QuantResult

logger = logging.getLogger(__name__)

# Canonical yfinance / Stooq symbols for macro market indicators.
# Direct SOFR rates are not quoted on yfinance; proxies are used:
#   sofr_on  — ^IRX (13-week T-bill yield, overnight rate proxy)
#   sofr_tn  — ZQ=F (30-day Fed Funds futures, tom/next proxy)
#   sofr_1m  — SR1=F (CME 1-month SOFR futures, term rate)
MACRO_SYMBOLS: dict[str, tuple[str, str]] = {
    "gold":        ("GC=F",    "Gold ($/oz)"),
    "crude_oil":   ("CL=F",    "WTI Crude Oil ($/bbl)"),
    "natural_gas": ("NG=F",    "Natural Gas ($/MMBtu)"),
    "sofr_on":     ("^IRX",    "SOFR Overnight (13-week T-bill proxy, %)"),
    "sofr_tn":     ("ZQ=F",    "SOFR Tom/Next (30-day Fed Funds futures proxy, %)"),
    "sofr_1m":     ("SR1=F",   "SOFR 1-Month (CME 1-month SOFR futures, %)"),
    "bitcoin":     ("BTC-USD", "Bitcoin (USD)"),
}

# US Bond yield tickers ordered by tenor (1-month → 6-month → 5-year → 10-year).
# ^US1MT and ^US6MT are Stooq symbols (datareader); ^FVX and ^TNX are yfinance CBOE indices.
BOND_TENORS: list[tuple[str, str]] = [
    ("^US1MT", "US Bond 1-Month Yield (%)"),
    ("^US6MT", "US Bond 6-Month Yield (%)"),
    ("^FVX",   "US Bond 5-Year Yield (%)"),
    ("^TNX",   "US Bond 10-Year Yield (%)"),
]


async def fetch_macro_ticker(
    qclient: QuantClient,
    symbol: str,
    label: str,
    thread_id: Optional[str],
    period: str = "2y",
    key: str = "",
    region: Optional[str] = None,
) -> MacroResult:
    """Fetch two years of daily OHLCV bars plus the current quote for a macro ticker.

    Uses ``source='auto'`` so the region-aware QuantClient selects the best
    available provider for the given region.  If the primary provider for the
    region does not support the macro symbol, the client walks the fallback
    chain automatically (e.g. akshare → alpha_vantage → yfinance for CN).

    Args:
        qclient:   Shared QuantClient instance.
        symbol:    Ticker symbol, e.g. 'GC=F' (gold), 'BTC-USD' (bitcoin).
        label:     Human-readable label for context lines.
        thread_id: LangGraph thread id.
        period:    yfinance period string for the fetch window (default '2y').
        key:       MACRO_SYMBOLS key for identification, e.g. 'gold'.
        region:    fin_markets.regions code (e.g. 'cn', 'us') for provider selection.

    Returns:
        :class:`MacroResult` with price, move statistics, and bar count.
    """
    try:
        ohlcv_result: QuantResult = await qclient.fetch(
            QuantQuery(
                symbol=symbol,
                method="periodic_ohlcv",
                params={"interval": "1d", "period": period},
                thread_id=thread_id,
                node_name="market_data_collector",
            ),
            source="auto",
            region=region,
        )
        bars = ohlcv_result.bars or []
        if not bars:
            return MacroResult(key=key, symbol=symbol, label=label, bars_count=0, source=ohlcv_result.source)
        last = bars[-1]
        result = MacroResult(
            key=key,
            symbol=symbol,
            label=label,
            latest_bar_date=last.date,
            latest_bar=last.model_dump(),
            bars_count=len(bars),
            source=ohlcv_result.source,
            bars=bars,
        )
        if len(bars) >= 5:
            prices = [b.close for b in bars[-5:]]
            pct = ((prices[-1] - prices[0]) / prices[0] * 100) if prices[0] else 0.0
            result = result.model_copy(update={"move_5d_pct": round(pct, 4)})
        if len(bars) >= 252:
            prices_1y = [b.close for b in bars]
            pct_1y = ((prices_1y[-1] - prices_1y[0]) / prices_1y[0] * 100) if prices_1y[0] else 0.0
            result = result.model_copy(update={"move_1y_pct": round(pct_1y, 4)})
        return result
    except Exception as exc:
        logger.warning("[quant tasks] macro fetch failed for %s (%s): %s", label, symbol, exc)
        return MacroResult(key=key, symbol=symbol, label=label, error=str(exc))


async def fetch_bond_yields(
    qclient: QuantClient,
    thread_id: Optional[str],
    period: str = "2y",
    region: Optional[str] = None,
) -> BondResult:
    """Fetch 2-year daily OHLCV bars for US Bond yield tenors (1-mo, 6-mo, 5-yr, 10-yr).

    Each tenor is fetched independently so a failure for one does not block
    the others.  Provider selection respects the ``region`` parameter so the
    region-aware QuantClient chain is used instead of always defaulting to
    yfinance.

    Args:
        qclient:   Shared QuantClient instance.
        thread_id: LangGraph thread id.
        period:    yfinance period string (default '2y').
        region:    fin_markets.regions code for provider selection.

    Returns:
        :class:`BondResult` with per-tenor :class:`OHLCVWindowResult` entries.
    """
    tenors: list[OHLCVWindowResult] = []
    for symbol, label in BOND_TENORS:
        try:
            result: QuantResult = await qclient.fetch(
                QuantQuery(
                    symbol=symbol,
                    method="periodic_ohlcv",
                    params={"interval": "1d", "period": period},
                    thread_id=thread_id,
                    node_name="market_data_collector",
                ),
                source="auto",
                region=region,
            )
            bars = result.bars or []
            tenors.append(OHLCVWindowResult(
                ticker=symbol,
                window="1day",
                label=label,
                bars=[b.model_dump() for b in bars],
                source=result.source,
            ))
        except Exception as exc:
            logger.warning("[quant tasks] treasury fetch failed for %s: %s", symbol, exc)
            tenors.append(OHLCVWindowResult(
                ticker=symbol,
                window="1day",
                label=label,
                error=str(exc),
            ))
    return BondResult(tenors=tenors)
