"""AKShare provider for quant market data — primarily for Chinese A-share markets.

AKShare wraps tushare / eastmoney / Sina Finance data sources and is the
preferred provider for:
  - A-share indices (000001.SS — Shanghai Composite, etc.)
  - A-share equities (600519.SH — Kweichow Moutai, etc.)
  - H-share / HK-listed Chinese companies

Symbol conventions used by AKShare:
  - A-share stock:     '600519'  (6-digit code — suffix stripped internally)
  - A-share index:     'sh000001' or '000001'
  - H-share via mktcap: passed as-is when AKShare supports it

Intervals supported:
  daily  → ak.stock_zh_a_hist(period='daily')
  weekly → ak.stock_zh_a_hist(period='weekly')
  monthly → ak.stock_zh_a_hist(period='monthly')
  intraday (60m) → ak.stock_zh_a_hist_min_em(period='60')
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import Any

from backend.resource_api.exceptions import ProviderNotFoundError
from backend.resource_api.quant_api.constants import PERIOD_DAYS
from backend.resource_api.quant_api.models import (
    OHLCVBar,
    PriceQuote,
    QuantQuery,
    QuantResult,
)

logger = logging.getLogger(__name__)

# Maps yfinance-style intervals → AKShare minute intervals
_INTRADAY_INTERVAL_MAP: dict[str, str] = {
    "1m":  "1",
    "5m":  "5",
    "15m": "15",
    "30m": "30",
    "60m": "60",
    "1h":  "60",
}

# Maps yfinance-style day intervals → AKShare period strings
_DAILY_PERIOD_MAP: dict[str, str] = {
    "1d":  "daily",
    "1wk": "weekly",
    "1mo": "monthly",
}

# ---------------------------------------------------------------------------
# Canonical-to-AKShare ticker translation map.
# AKShare is China-centric.  Chinese A-share indices are translated to their
# bare 6-digit codes (without the .SS / .SZ exchange suffix which AKShare
# does not use).  All international and commodity tickers are set to None to
# cause the client to fall through to yfinance / datareader.
# ---------------------------------------------------------------------------
TICKER_MAP: dict[str, str | None] = {
    # Chinese A-share indices — strip exchange suffix to bare code
    "000001.SS":  "000001",   # Shanghai Composite (SSE)
    "399001.SZ":  "399001",   # Shenzhen Component (SZSE)
    "399006.SZ":  "399006",   # ChiNext (SZSE)
    "000300.SS":  "000300",   # CSI 300
    "^SSEC":      "000001",   # Alternative canonical for Shanghai Composite
    # HK — AKShare supports HSI via ak.index_global, but limited; prefer yfinance
    "^HSI":       None,
    "^HSCE":      None,
    # Commodity futures — not available in AKShare
    "GC=F":       None,
    "CL=F":       None,
    "NG=F":       None,
    "BZ=F":       None,
    "SI=F":       None,
    "HG=F":       None,
    # Treasury / CBOE yield indices — not in AKShare
    "^IRX":       None,
    "^TNX":       None,
    "^TYX":       None,
    "^FVX":       None,
    "^US1MT":     None,
    "^US6MT":     None,
    # US equity indices — not supported by AKShare
    "^GSPC":      None,
    "^IXIC":      None,
    "^NDX":       None,
    "^DJI":       None,
    "^RUT":       None,
    # Other international indices — not supported
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
    # Crypto — not supported
    "BTC-USD":    None,
    "ETH-USD":    None,
}


def _strip_suffix(symbol: str) -> str:
    """Remove exchange suffixes (.SS, .SZ, .SH, .HK) from a ticker.

    AKShare expects bare 6-digit codes for A-share stocks.

    Args:
        symbol: Raw ticker symbol, e.g. ``'600519.SS'``.

    Returns:
        Bare code, e.g. ``'600519'``.
    """
    for sep in (".", "-"):
        if sep in symbol:
            return symbol.split(sep)[0]
    return symbol


def _parse_period_dates(params: dict[str, Any]) -> tuple[str, str]:
    """Derive start/end date strings for AKShare from query params.

    Args:
        params: Query params dict from QuantQuery (may contain 'period' or 'start').

    Returns:
        Tuple of (start_date, end_date) as ``'YYYYMMDD'`` strings.
    """
    from datetime import timedelta  # noqa: PLC0415

    end_dt = datetime.now(timezone.utc)
    end_str = end_dt.strftime("%Y%m%d")

    if "start" in params:
        try:
            start_dt = datetime.fromisoformat(params["start"].replace("Z", "+00:00"))
            return start_dt.strftime("%Y%m%d"), end_str
        except (ValueError, AttributeError):
            pass

    period = params.get("period", "3mo")
    days = PERIOD_DAYS.get(period, 90)
    start_dt = end_dt - timedelta(days=days)
    return start_dt.strftime("%Y%m%d"), end_str


def _fetch_stock_ohlcv(symbol: str, params: dict[str, Any]) -> QuantResult:
    """Fetch A-share stock OHLCV bars via AKShare (blocking).

    Uses ``ak.stock_zh_a_hist`` for daily/weekly/monthly, and
    ``ak.stock_zh_a_hist_min_em`` for intraday bars.

    Args:
        symbol: Ticker symbol (e.g. ``'600519.SS'`` or ``'600519'``).
        params: Query params containing interval, period, start, etc.

    Returns:
        Normalised :class:`QuantResult` with OHLCV bars.

    Raises:
        ProviderNotFoundError: When AKShare returns an empty DataFrame.
    """
    import akshare as ak  # type: ignore[import]  # noqa: PLC0415

    bare = _strip_suffix(symbol)
    interval = params.get("interval", "1d")
    start_date, end_date = _parse_period_dates(params)

    if interval in _INTRADAY_INTERVAL_MAP:
        period_str = _INTRADAY_INTERVAL_MAP[interval]
        df = ak.stock_zh_a_hist_min_em(
            symbol=bare,
            period=period_str,
            start_date=f"{start_date[:4]}-{start_date[4:6]}-{start_date[6:]}",
            end_date=f"{end_date[:4]}-{end_date[4:6]}-{end_date[6:]}",
            adjust="qfq",
        )
        if df is None or df.empty:
            raise ProviderNotFoundError("akshare", f"stock_zh_a_hist_min_em/{interval}", symbol, "empty DataFrame")
        bars = [
            OHLCVBar(
                date=str(row["时间"]),
                open=round(float(row["开盘"]), 6),
                high=round(float(row["最高"]), 6),
                low=round(float(row["最低"]), 6),
                close=round(float(row["收盘"]), 6),
                volume=int(row["成交量"]),
            )
            for _, row in df.iterrows()
        ]
    else:
        period_str = _DAILY_PERIOD_MAP.get(interval, "daily")
        df = ak.stock_zh_a_hist(
            symbol=bare,
            period=period_str,
            start_date=start_date,
            end_date=end_date,
            adjust="qfq",
        )
        if df is None or df.empty:
            raise ProviderNotFoundError("akshare", f"stock_zh_a_hist/{period_str}", symbol, "empty DataFrame")
        bars = [
            OHLCVBar(
                date=str(row["日期"]),
                open=round(float(row["开盘"]), 6),
                high=round(float(row["最高"]), 6),
                low=round(float(row["最低"]), 6),
                close=round(float(row["收盘"]), 6),
                volume=int(row["成交量"]),
            )
            for _, row in df.iterrows()
        ]

    return QuantResult(
        symbol=symbol.upper(),
        method="periodic_ohlcv",
        source="akshare",
        bars=bars,
        fetched_at=datetime.now(timezone.utc),
    )


def _fetch_index_ohlcv(symbol: str, params: dict[str, Any]) -> QuantResult:
    """Fetch A-share index OHLCV bars via AKShare (blocking).

    Uses ``ak.stock_zh_index_daily`` or ``ak.index_zh_a_hist`` depending on
    availability.  The symbol should be the bare 6-digit code (e.g. ``'000001'``
    for Shanghai Composite).

    Args:
        symbol: Index symbol (e.g. ``'000001.SS'`` or ``'^SSEC'``).
        params: Query params.

    Returns:
        Normalised :class:`QuantResult`.

    Raises:
        ProviderNotFoundError: On empty result.
    """
    import akshare as ak  # type: ignore[import]  # noqa: PLC0415

    bare = _strip_suffix(symbol).lstrip("^")
    start_date, end_date = _parse_period_dates(params)

    try:
        df = ak.index_zh_a_hist(
            symbol=bare,
            period="daily",
            start_date=start_date,
            end_date=end_date,
        )
    except Exception:
        # Fallback to the older daily endpoint
        df = ak.stock_zh_index_daily(symbol=f"sh{bare}" if bare.startswith("0") else f"sz{bare}")

    if df is None or df.empty:
        raise ProviderNotFoundError("akshare", "index_zh_a_hist", symbol, "empty DataFrame")

    # Column names vary between endpoints — normalise
    col_map = {
        "日期": "date", "date": "date",
        "开盘": "open",  "open": "open",
        "最高": "high",  "high": "high",
        "最低": "low",   "low": "low",
        "收盘": "close", "close": "close",
        "成交量": "volume", "volume": "volume",
    }
    df = df.rename(columns=col_map)
    bars = [
        OHLCVBar(
            date=str(row["date"]),
            open=round(float(row["open"]), 6),
            high=round(float(row["high"]), 6),
            low=round(float(row["low"]), 6),
            close=round(float(row["close"]), 6),
            volume=int(row.get("volume", 0)),
        )
        for _, row in df.iterrows()
    ]
    return QuantResult(
        symbol=symbol.upper(),
        method="periodic_ohlcv",
        source="akshare",
        bars=bars,
        fetched_at=datetime.now(timezone.utc),
    )


def _fetch_overview(symbol: str) -> QuantResult:
    """Return exchange / market metadata for an A-share or H-share symbol.

    AKShare does not have a single company-overview endpoint, so the exchange
    is inferred deterministically from the 6-digit code prefix:

    - 60xxxx, 68xxxx, 51xxxx  → SSE  (Shanghai Stock Exchange)
    - 00xxxx, 30xxxx, 20xxxx  → SZSE (Shenzhen Stock Exchange)
    - .HK suffix              → HKEX (Hong Kong Stock Exchange)

    Args:
        symbol: Ticker symbol, e.g. ``'600519.SS'`` or ``'9988.HK'``.

    Returns:
        :class:`QuantResult` with ``overview={"exchange": "SSE"|"SZSE"|"HKEX"}"

    Raises:
        ProviderNotFoundError: When the exchange cannot be inferred.
    """
    upper = symbol.upper()
    if upper.endswith(".HK"):
        exchange = "HKEX"
    else:
        bare = _strip_suffix(symbol)
        if bare.startswith(("60", "68", "51", "11")):
            exchange = "SSE"
        elif bare.startswith(("00", "30", "20", "10")):
            exchange = "SZSE"
        else:
            raise ProviderNotFoundError(
                "akshare", "overview", symbol,
                f"cannot infer exchange from code prefix {bare[:2]!r}",
            )
    return QuantResult(
        symbol=symbol.upper(),
        method="overview",
        source="akshare",
        overview={"exchange": exchange, "market": "cn"},
        fetched_at=datetime.now(timezone.utc),
    )


def _fetch_quote(symbol: str) -> QuantResult:
    """Fetch current A-share spot price via AKShare (blocking).

    Args:
        symbol: Ticker symbol, e.g. ``'600519.SS'``.

    Returns:
        :class:`QuantResult` with a :class:`PriceQuote`.

    Raises:
        ProviderNotFoundError: When the symbol is not found.
    """
    import akshare as ak  # type: ignore[import]  # noqa: PLC0415

    bare = _strip_suffix(symbol)
    df = ak.stock_zh_a_spot_em()  # full A-share snapshot (all tickers)
    if df is None or df.empty:
        raise ProviderNotFoundError("akshare", "stock_zh_a_spot_em", symbol, "empty snapshot")

    row = df[df["代码"] == bare]
    if row.empty:
        raise ProviderNotFoundError("akshare", "stock_zh_a_spot_em", symbol, f"code {bare!r} not in snapshot")

    r = row.iloc[0]
    price = float(r.get("最新价", 0) or 0)
    if not price:
        raise ProviderNotFoundError("akshare", "stock_zh_a_spot_em", symbol, "price=0")

    change_pct_raw = r.get("涨跌幅", 0)
    quote = PriceQuote(
        symbol=symbol.upper(),
        price=price,
        change=float(r.get("涨跌额", 0) or 0),
        change_pct=float(change_pct_raw or 0),
        volume=int(r.get("成交量", 0) or 0) or None,
        market_cap=float(r.get("总市值", 0) or 0) or None,
        timestamp=datetime.now(timezone.utc).isoformat(),
    )
    return QuantResult(
        symbol=symbol.upper(),
        method="quote",
        source="akshare",
        quote=quote,
        fetched_at=datetime.now(timezone.utc),
    )


async def fetch(query: QuantQuery) -> QuantResult:
    """Dispatch a QuantQuery to the appropriate AKShare function.

    All AKShare calls are blocking; they are executed in a thread pool via
    ``asyncio.to_thread`` to avoid blocking the event loop.

    Args:
        query: Structured market-data query.

    Returns:
        Normalised :class:`QuantResult`.

    Raises:
        ProviderNotFoundError: When the requested data is unavailable.
        ValueError: For unsupported method/interval combinations.
    """
    symbol = query.symbol

    if query.method == "overview":
        return await asyncio.to_thread(_fetch_overview, symbol)

    if query.method == "quote":
        return await asyncio.to_thread(_fetch_quote, symbol)

    if query.method in ("daily_ohlcv", "intraday_ohlcv", "periodic_ohlcv"):
        # Choose index vs stock path based on symbol format
        bare = _strip_suffix(symbol).lstrip("^")
        is_index = symbol.startswith("^") or (bare.isdigit() and len(bare) == 6 and bare.startswith(("0000", "399", "399")))
        if is_index:
            return await asyncio.to_thread(_fetch_index_ohlcv, symbol, query.params)
        return await asyncio.to_thread(_fetch_stock_ohlcv, symbol, query.params)

    raise ProviderNotFoundError(
        "akshare", query.method, query.symbol,
        f"method {query.method!r} is not supported by the akshare provider",
    )
