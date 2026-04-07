"""IngestMixin — provider-agnostic data ingestion methods.

Mixed into ``MarketDataService``.  Assumes the host class provides:
  ``_client``, ``_fallback_client``, ``_ext_call()``, ``_effective_provider()``,
  ``_to_security()``, ``_to_entity()``, ``_to_news()``,
  ``_to_security_ext()``, ``_to_ext_aggreg()``,
  ``_sec_repo``, ``_fund_repo``, ``_trade_repo``, ``_news_repo``.
"""

import logging
from datetime import date, datetime
from typing import TYPE_CHECKING, Any

from app.models.markets.securities import SecurityRecord
from app.models.markets.fundamentals import SecurityExtRecord
from app.quant_api import transforms

if TYPE_CHECKING:
    from app.quant_api.service import MarketDataService

logger = logging.getLogger(__name__)


class IngestMixin:
    """Ingest methods that persist external API data into the database."""

    async def ingest_profile(self: "MarketDataService", symbol: str) -> SecurityRecord | None:
        """Fetch company profile and upsert into securities + entities + exts.

        DB-first: returns cached DB record when today's snapshot already exists.
        Falls back from yfinance to FMP when primary returns no data.

        After a successful API call the profile is split across:
        ``securities`` → ``entities`` → ``security_exts`` → ``security_ext_aggregs``.

        Args:
            symbol: Ticker symbol (e.g. ``'AAPL'``).

        Returns:
            Upserted ``SecurityRecord``, or ``None`` if all providers returned
            no data.
        """
        # ── DB-first check ──────────────────────────────────────────────
        db_row = await self._sec_repo.get_security(symbol)
        if db_row:
            ext_row = await self._fund_repo.get_security_ext_today(db_row["id"])
            if ext_row:
                logger.info("Profile DB-hit for %s (security_id=%d)", symbol, db_row["id"])
                return SecurityRecord(
                    **{k: v for k, v in db_row.items() if k in SecurityRecord.model_fields}
                )

        # ── External API call ───────────────────────────────────────────
        used_client = self._client
        raw: dict[str, Any] | None = await self._ext_call(
            self._client,
            "get_company_profile",
            {"symbol": symbol},
            lambda: self._client.get_company_profile(symbol),
        )
        if not raw and self._fallback_client:
            logger.info("yfinance profile empty for %s, trying FMP fallback", symbol)
            used_client = self._fallback_client
            raw = await self._ext_call(
                self._fallback_client,
                "get_company_profile",
                {"symbol": symbol},
                lambda: self._fallback_client.get_company_profile(symbol),
            )
        if not raw:
            logger.warning("No profile data for %s from any provider", symbol)
            return None

        # ── Persist: securities ─────────────────────────────────────────
        sec = self._to_security(raw, used_client)
        await self._sec_repo.upsert_security(sec)
        db_sec = await self._sec_repo.get_security(symbol)
        if not db_sec:
            return sec
        security_id: int = db_sec["id"]
        sec.id = security_id

        # ── Persist: entities ───────────────────────────────────────────
        entity = self._to_entity(raw, used_client)
        ipo_raw = raw.get("ipoDate")
        if ipo_raw and not entity.established_at:
            try:
                if isinstance(ipo_raw, (int, float)):
                    entity.established_at = datetime.utcfromtimestamp(ipo_raw).date()
                else:
                    entity.established_at = date.fromisoformat(str(ipo_raw)[:10])
            except Exception:
                pass
        if entity.industry is None and raw.get("sector"):
            entity.industry = transforms._SECTOR_MAP.get(raw["sector"])
        await self._sec_repo.upsert_entity(entity)

        # ── Persist: security_exts + security_ext_aggregs ───────────────
        p = self._effective_provider(used_client)
        ext = (
            transforms.fmp_profile_to_security_ext(raw, security_id)
            if p == "fmp"
            else transforms.yf_profile_to_security_ext(raw, security_id)
        )
        if any([ext.price, ext.market_cap_usd, ext.pe_ratio, ext.dividend_yield]):
            ext_id = await self._fund_repo.upsert_security_ext(ext)
            if ext_id:
                aggreg = (
                    transforms.fmp_profile_to_ext_aggreg(raw, ext_id)
                    if p == "fmp"
                    else transforms.yf_profile_to_ext_aggreg(raw, ext_id)
                )
                await self._fund_repo.upsert_security_ext_aggreg(aggreg)

        logger.info("Ingested profile for %s via %s", symbol, self._effective_provider(used_client))
        return sec

    async def ingest_trades(
        self: "MarketDataService",
        symbol: str,
        from_date: date,
        to_date: date,
        interval: str = "1d",
    ) -> int:
        """Fetch OHLCV bars and insert into fin_markets.security_trades.

        DB-first: skips the API call when the date range is already covered.

        Args:
            symbol: Ticker symbol.
            from_date: Start date (inclusive).
            to_date: End date (inclusive).
            interval: Bar interval code (default ``'1d'``).

        Returns:
            Number of bars inserted (0 when served from DB).
        """
        db_sec = await self._sec_repo.get_security(symbol)
        if not db_sec:
            logger.error("Security '%s' not in DB — call ingest_profile first", symbol)
            return 0
        security_id: int = db_sec["id"]

        # ── DB-first check ──────────────────────────────────────────────
        if await self._trade_repo.is_covered(security_id, from_date, to_date, interval):
            logger.info("Trades DB-hit for %s %s→%s", symbol, from_date, to_date)
            return 0

        # ── External API call ───────────────────────────────────────────
        _params = {
            "symbol": symbol,
            "from_date": str(from_date),
            "to_date": str(to_date),
            "interval": interval,
        }
        bars: list[dict[str, Any]] = await self._ext_call(
            self._client,
            "get_historical_prices",
            _params,
            lambda: self._client.get_historical_prices(symbol, from_date, to_date, interval),
        ) or []
        if not bars and self._fallback_client:
            logger.info("yfinance prices empty for %s, trying FMP fallback", symbol)
            bars = await self._ext_call(
                self._fallback_client,
                "get_historical_prices",
                _params,
                lambda: self._fallback_client.get_historical_prices(
                    symbol, from_date, to_date, interval
                ),
            ) or []
        if not bars:
            logger.warning("No price data for %s from any provider", symbol)
            return 0

        records = transforms.bars_to_trades(bars, security_id, interval)
        for rec in records:
            await self._trade_repo.upsert_trade(rec)

        logger.info("Ingested %d trade bars for %s", len(records), symbol)
        return len(records)

    async def ingest_news(
        self: "MarketDataService",
        symbol: str | None = None,
        limit: int = 50,
    ) -> int:
        """Fetch news articles and insert into fin_markets.news.

        DB-first: skips the API when recent articles (within 4 hours) exist.

        Args:
            symbol: Optional ticker to filter news.
            limit: Maximum number of articles to fetch.

        Returns:
            Number of articles inserted (0 when served from DB).
        """
        if symbol:
            db_articles = await self._news_repo.get_recent(symbol, hours=4, limit=limit)
            if db_articles:
                logger.info("News DB-hit for %s (%d articles)", symbol, len(db_articles))
                return 0

        _params: dict[str, Any] = {"symbol": symbol, "limit": limit}
        used_client = self._client
        articles: list[dict[str, Any]] = await self._ext_call(
            self._client,
            "get_stock_news",
            _params,
            lambda: self._client.get_stock_news(symbol=symbol, limit=limit),
        ) or []
        if not articles and self._fallback_client:
            logger.info("yfinance news empty for %s, trying FMP fallback", symbol)
            used_client = self._fallback_client
            articles = await self._ext_call(
                self._fallback_client,
                "get_stock_news",
                _params,
                lambda: self._fallback_client.get_stock_news(symbol=symbol, limit=limit),
            ) or []

        count = 0
        for article in articles:
            rec = self._to_news(article, used_client)
            await self._news_repo.upsert_news(rec)
            count += 1

        logger.info("Ingested %d news articles", count)
        return count

    async def ingest_metrics(
        self: "MarketDataService",
        symbol: str,
        security_id: int,
    ) -> SecurityExtRecord | None:
        """Fetch key metrics + ratios and insert into security_exts.

        DB-first: returns today's snapshot if already stored.

        Args:
            symbol: Ticker symbol.
            security_id: FK to fin_markets.securities (from ``ingest_profile``).

        Returns:
            Existing or inserted ``SecurityExtRecord``, or ``None`` on failure.
        """
        ext_row = await self._fund_repo.get_security_ext_today(security_id)
        if ext_row:
            logger.info("Metrics DB-hit for %s (security_id=%d)", symbol, security_id)
            return SecurityExtRecord(
                id=ext_row["id"],
                security_id=security_id,
                published_at=ext_row["published_at"],
                price=ext_row.get("price"),
                market_cap_usd=ext_row.get("market_cap_usd"),
                pe_ratio=ext_row.get("pe_ratio"),
                pb_ratio=ext_row.get("pb_ratio"),
                net_margin=ext_row.get("net_margin"),
                eps_ttm=ext_row.get("eps_ttm"),
                revenue_ttm=ext_row.get("revenue_ttm"),
                debt_to_equity=ext_row.get("debt_to_equity"),
                dividend_yield=ext_row.get("dividend_yield"),
            )

        # ── External API call ───────────────────────────────────────────
        used_client = self._client
        metrics: dict[str, Any] = await self._ext_call(
            self._client,
            "get_key_metrics",
            {"symbol": symbol},
            lambda: self._client.get_key_metrics(symbol),
        ) or {}
        ratios: dict[str, Any] = await self._ext_call(
            self._client,
            "get_financial_ratios",
            {"symbol": symbol},
            lambda: self._client.get_financial_ratios(symbol),
        ) or {}
        if not metrics and not ratios and self._fallback_client:
            logger.info("yfinance metrics empty for %s, trying FMP fallback", symbol)
            used_client = self._fallback_client
            metrics = await self._ext_call(
                self._fallback_client,
                "get_key_metrics",
                {"symbol": symbol},
                lambda: self._fallback_client.get_key_metrics(symbol),
            ) or {}
            ratios = await self._ext_call(
                self._fallback_client,
                "get_financial_ratios",
                {"symbol": symbol},
                lambda: self._fallback_client.get_financial_ratios(symbol),
            ) or {}
        if not metrics and not ratios:
            logger.warning("No metrics data for %s from any provider", symbol)
            return None

        ext = self._to_security_ext(metrics, ratios, security_id, used_client)
        ext_id = await self._fund_repo.upsert_security_ext(ext)
        if ext_id:
            ext.id = ext_id
            aggreg = self._to_ext_aggreg(metrics, ratios, ext_id, used_client)
            await self._fund_repo.upsert_security_ext_aggreg(aggreg)

        logger.info("Ingested fundamentals for security_id=%d", security_id)
        return ext
