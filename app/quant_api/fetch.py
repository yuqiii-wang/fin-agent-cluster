"""FetchMixin — context-string fetch methods for LLM agent nodes.

Mixed into ``MarketDataService``.  All methods return formatted plain-text
strings ready to be injected into LLM prompts.

Assumes the host class provides:
  ``_client``, ``_fallback_client``, ``_ext_call()``,
  ``_sec_repo``, ``_fund_repo``, ``_trade_repo``, ``_news_repo``,
  ``_to_news()``.
"""

import logging
from datetime import date
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from app.quant_api.service import MarketDataService

logger = logging.getLogger(__name__)


class FetchMixin:
    """Read-only fetch methods that build formatted context strings for LLM prompts."""

    async def fetch_price_context(
        self: "MarketDataService",
        symbol: str,
        from_date: date,
        to_date: date,
    ) -> str:
        """Return a text summary of recent OHLCV bars and the current quote.

        DB-first: reads from fin_markets.security_trades when the range is
        already stored.  Falls back to a live API call otherwise.

        Args:
            symbol: Ticker symbol.
            from_date: Start date for historical bars.
            to_date: End date for historical bars.

        Returns:
            Multi-line string with quote snapshot and recent OHLCV table.
        """
        def _fmt_bars(bar_rows: list[dict]) -> list[str]:
            lines: list[str] = ["\nDate        Open     High     Low      Close    Volume"]
            for b in bar_rows[-20:]:
                d = str(b.get("trade_date") or b.get("date", ""))[:10]
                lines.append(
                    f"{d:<12}"
                    f"{float(b.get('open', 0)):>8.2f}"
                    f"{float(b.get('high', 0)):>9.2f}"
                    f"{float(b.get('low', 0)):>9.2f}"
                    f"{float(b.get('close', 0)):>9.2f}"
                    f"{int(b.get('volume') or 0):>12}"
                )
            return lines

        lines = [f"=== Market Data: {symbol} ==="]

        # ── Quote: try DB security_exts first ──────────────────────────
        db_sec = await self._sec_repo.get_security(symbol)
        if db_sec:
            ext_row = await self._fund_repo.get_security_ext_today(db_sec["id"])
            if ext_row and ext_row.get("price"):
                lines += [
                    f"Price     : {ext_row['price']}",
                    f"Market Cap: {ext_row.get('market_cap_usd', 'N/A')}",
                    f"P/E       : {ext_row.get('pe_ratio', 'N/A')}",
                    f"Beta      : {ext_row.get('beta', 'N/A')}",
                ]

        # ── Bars: try DB security_trades first ─────────────────────────
        if db_sec:
            if await self._trade_repo.is_covered(db_sec["id"], from_date, to_date):
                db_bars = await self._trade_repo.get_trades(db_sec["id"], from_date, to_date)
                if db_bars:
                    logger.info("Price context DB-hit for %s", symbol)
                    lines += _fmt_bars(db_bars)
                    return "\n".join(lines) if len(lines) > 1 else f"No price data available for {symbol}."

        # ── Live API fallback ──────────────────────────────────────────
        quote = await self._ext_call(
            self._client,
            "get_quote",
            {"symbol": symbol},
            lambda: self._client.get_quote(symbol),
        )
        if not quote and self._fallback_client:
            quote = await self._ext_call(
                self._fallback_client,
                "get_quote",
                {"symbol": symbol},
                lambda: self._fallback_client.get_quote(symbol),
            )

        _price_params = {
            "symbol": symbol,
            "from_date": str(from_date),
            "to_date": str(to_date),
            "interval": "1d",
        }
        bars = await self._ext_call(
            self._client,
            "get_historical_prices",
            _price_params,
            lambda: self._client.get_historical_prices(symbol, from_date, to_date),
        )
        if not bars and self._fallback_client:
            bars = await self._ext_call(
                self._fallback_client,
                "get_historical_prices",
                _price_params,
                lambda: self._fallback_client.get_historical_prices(symbol, from_date, to_date),
            )

        if quote:
            lines += [
                f"Price     : {quote.get('price')}",
                f"Change    : {quote.get('change')} ({quote.get('changesPercentage')}%)",
                f"Volume    : {quote.get('volume')}",
                f"Market Cap: {quote.get('marketCap')}",
                f"52w High  : {quote.get('52WeekHigh')}",
                f"52w Low   : {quote.get('52WeekLow')}",
            ]
        if bars:
            lines += _fmt_bars(bars)
        return "\n".join(lines) if len(lines) > 1 else f"No price data available for {symbol}."

    async def fetch_fundamentals_context(self: "MarketDataService", symbol: str) -> str:
        """Return a text summary of key financial metrics and ratios.

        DB-first: reads from security_exts + security_ext_aggregs when
        today's snapshot is available.  On live API fetch, persists the
        results back to DB so the next call is served from cache.

        Args:
            symbol: Ticker symbol.

        Returns:
            Multi-line string with fundamental metrics.
        """
        def _fmt(v: Any) -> str:
            if v is None:
                return "N/A"
            try:
                return f"{float(v):.4f}"
            except (TypeError, ValueError):
                return str(v)

        def _build_lines(row: dict) -> list[str]:
            return [
                f"=== Fundamentals: {symbol} ===",
                f"Price              : {_fmt(row.get('price'))}",
                f"Market Cap         : {_fmt(row.get('market_cap_usd'))}",
                f"P/E (TTM)          : {_fmt(row.get('pe_ratio'))}",
                f"P/E (Forward)      : {_fmt(row.get('pe_forward'))}",
                f"P/B                : {_fmt(row.get('pb_ratio'))}",
                f"P/S                : {_fmt(row.get('ps_ratio'))}",
                f"EV/EBITDA          : {_fmt(row.get('ev_ebitda'))}",
                f"PEG                : {_fmt(row.get('peg_ratio'))}",
                f"EPS (TTM)          : {_fmt(row.get('eps_ttm'))}",
                f"EPS Diluted        : {_fmt(row.get('eps_diluted'))}",
                f"Revenue TTM        : {_fmt(row.get('revenue_ttm'))}",
                f"EBITDA TTM         : {_fmt(row.get('ebitda_ttm'))}",
                f"Net Income TTM     : {_fmt(row.get('net_income_ttm'))}",
                f"ROE                : {_fmt(row.get('roe'))}",
                f"ROA                : {_fmt(row.get('roa'))}",
                f"Gross Margin       : {_fmt(row.get('gross_margin'))}",
                f"Operating Margin   : {_fmt(row.get('operating_margin'))}",
                f"Net Margin         : {_fmt(row.get('net_margin'))}",
                f"Debt/Equity        : {_fmt(row.get('debt_to_equity'))}",
                f"Total Debt         : {_fmt(row.get('total_debt'))}",
                f"Total Cash         : {_fmt(row.get('total_cash'))}",
                f"Current Ratio      : {_fmt(row.get('current_ratio'))}",
                f"Quick Ratio        : {_fmt(row.get('quick_ratio'))}",
                f"Book Value/Share   : {_fmt(row.get('book_value_ps'))}",
                f"Dividend Yield     : {_fmt(row.get('dividend_yield'))}",
                f"Payout Ratio       : {_fmt(row.get('payout_ratio'))}",
                f"Beta               : {_fmt(row.get('beta'))}",
                f"Shares Outstanding : {_fmt(row.get('shares_outstanding'))}",
                f"Analyst Target     : {_fmt(row.get('analyst_target_price'))}",
            ]

        db_sec = await self._sec_repo.get_security(symbol)
        if db_sec:
            ext_row = await self._fund_repo.get_security_ext_today(db_sec["id"])
            if ext_row and any(
                ext_row.get(c) is not None for c in ("pe_ratio", "market_cap_usd", "beta")
            ):
                logger.info("Fundamentals DB-hit for %s", symbol)
                return "\n".join(_build_lines(ext_row))

        # ── Live API fallback ──────────────────────────────────────────
        metrics = await self._ext_call(
            self._client,
            "get_key_metrics",
            {"symbol": symbol},
            lambda: self._client.get_key_metrics(symbol),
        )
        ratios = await self._ext_call(
            self._client,
            "get_financial_ratios",
            {"symbol": symbol},
            lambda: self._client.get_financial_ratios(symbol),
        )
        if not metrics and not ratios and self._fallback_client:
            metrics = await self._ext_call(
                self._fallback_client,
                "get_key_metrics",
                {"symbol": symbol},
                lambda: self._fallback_client.get_key_metrics(symbol),
            )
            ratios = await self._ext_call(
                self._fallback_client,
                "get_financial_ratios",
                {"symbol": symbol},
                lambda: self._fallback_client.get_financial_ratios(symbol),
            )

        if not metrics and not ratios:
            return f"No fundamental data available for {symbol}."

        m, r = metrics or {}, ratios or {}

        # ── Persist live metrics back to DB ────────────────────────────
        if db_sec:
            from app.quant_api import transforms
            security_id: int = db_sec["id"]
            p = self._effective_provider(self._client)
            ext = (
                transforms.fmp_metrics_to_security_ext(m, r, security_id)
                if p == "fmp"
                else transforms.yf_metrics_to_security_ext(m, r, security_id)
            )
            try:
                ext_id = await self._fund_repo.upsert_security_ext(ext)
                if ext_id:
                    aggreg = (
                        transforms.fmp_metrics_to_ext_aggreg(m, r, ext_id)
                        if p == "fmp"
                        else transforms.yf_metrics_to_ext_aggreg(m, r, ext_id)
                    )
                    await self._fund_repo.upsert_security_ext_aggreg(aggreg)
                    logger.info("Persisted live metrics for %s to DB (ext_id=%s)", symbol, ext_id)
            except Exception as exc:
                logger.warning("Failed to persist live metrics for %s: %s", symbol, exc)

        lines = [
            f"=== Fundamentals: {symbol} ===",
            f"P/E (TTM)          : {_fmt(m.get('peRatio') or m.get('peRatioTTM'))}",
            f"P/E (Forward)      : {_fmt(m.get('forwardPE'))}",
            f"P/B                : {_fmt(m.get('pbRatio') or m.get('pbRatioTTM'))}",
            f"P/S                : {_fmt(m.get('psRatio') or m.get('priceToSalesRatioTTM'))}",
            f"EV/EBITDA          : {_fmt(m.get('ev_ebitda') or m.get('enterpriseValueOverEBITDATTM'))}",
            f"ROE                : {_fmt(m.get('roe') or r.get('returnOnEquityTTM'))}",
            f"ROA                : {_fmt(m.get('roa') or r.get('returnOnAssetsTTM'))}",
            f"Gross Margin       : {_fmt(r.get('grossProfitMargin') or r.get('grossProfitMarginTTM'))}",
            f"Operating Margin   : {_fmt(r.get('operatingProfitMargin') or r.get('operatingProfitMarginTTM'))}",
            f"Net Margin         : {_fmt(r.get('netProfitMargin') or r.get('netProfitMarginTTM'))}",
            f"Debt/Equity        : {_fmt(m.get('debtToEquity') or m.get('debtToEquityTTM'))}",
            f"Current Ratio      : {_fmt(m.get('currentRatio'))}",
            f"Quick Ratio        : {_fmt(m.get('quickRatio'))}",
            f"Dividend Yield     : {_fmt(m.get('dividendYield') or m.get('dividendYieldTTM'))}",
            f"Payout Ratio       : {_fmt(m.get('payoutRatio'))}",
            f"Beta               : {_fmt(m.get('beta'))}",
            f"Revenue Growth YoY : {_fmt(r.get('revenueGrowth'))}",
            f"Earnings Growth YoY: {_fmt(r.get('earningsGrowth'))}",
        ]
        return "\n".join(lines)

    async def fetch_news_context(
        self: "MarketDataService",
        symbol: str,
        limit: int = 15,
    ) -> str:
        """Return a numbered list of recent news headlines for the symbol.

        DB-first: reads from fin_markets.news when recent articles exist.
        Falls back to live API otherwise.

        Args:
            symbol: Ticker symbol.
            limit: Maximum number of articles to return.

        Returns:
            Numbered list of headlines with publisher and date.
        """
        def _format_lines(articles_raw: list[dict]) -> list[str]:
            lines = [f"=== Recent News: {symbol} ==="]
            for i, a in enumerate(articles_raw[:limit], 1):
                date_str = str(
                    a.get("published_at") or a.get("publishedDate") or ""
                )[:10]
                publisher = (
                    a.get("publisher") or a.get("site") or a.get("data_source") or ""
                )
                title = a.get("title", "")
                lines.append(f"{i:>2}. [{date_str}] {title}  ({publisher})")
            return lines

        db_news = await self._news_repo.get_recent(symbol, hours=6, limit=limit)
        if db_news:
            logger.info("News context DB-hit for %s (%d articles)", symbol, len(db_news))
            return "\n".join(_format_lines(db_news))

        _news_params: dict[str, Any] = {"symbol": symbol, "limit": limit}
        articles = await self._ext_call(
            self._client,
            "get_stock_news",
            _news_params,
            lambda: self._client.get_stock_news(symbol=symbol, limit=limit),
        )
        if not articles and self._fallback_client:
            logger.info("yfinance news empty for %s, trying FMP fallback", symbol)
            articles = await self._ext_call(
                self._fallback_client,
                "get_stock_news",
                _news_params,
                lambda: self._fallback_client.get_stock_news(symbol=symbol, limit=limit),
            )

        if not articles:
            return f"No recent news found for {symbol}."
        return "\n".join(_format_lines(articles))
