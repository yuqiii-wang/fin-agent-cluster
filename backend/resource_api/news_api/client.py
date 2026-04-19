"""Unified news client with 4-hour DB-backed cache (fin_markets.news_raw)."""

from __future__ import annotations

import hashlib
import json
import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from backend.config import get_settings
from backend.db import raw_conn
from backend.db.postgres.queries.fin_markets_news import NewsRawSQL
from backend.resource_api.exceptions import ProviderNotFoundError
from backend.resource_api.mem_cache import TimedLRUCache
from backend.resource_api.news_api.models import NewsQuery, NewsResult, NewsSource
from backend.resource_api.news_api.providers import alpha_vantage_news, web_search, yfinance_news

logger = logging.getLogger(__name__)

_CACHE_TTL_HOURS = 4
# L1: in-memory cache — 1-hour TTL, evicted before the 4-hour DB cache expires.
_mem_cache: TimedLRUCache = TimedLRUCache()

# Fallback order when the requested source fails.
# Key = primary source; value = ordered list of sources to try next.
_FALLBACK_CHAINS: dict[str, list[str]] = {
    "yfinance":      ["alpha_vantage", "web_search"],
    "alpha_vantage": ["yfinance",      "web_search"],
    "web_search":    ["alpha_vantage", "yfinance"],
}


def _make_cache_key(source: str, query: NewsQuery) -> str:
    """Produce a deterministic sha256 cache key for the given source + query."""
    payload = json.dumps(
        {
            "source": source,
            "method": query.method,
            "symbol": (query.symbol or "").upper(),
            "query": query.query or "",
            "params": query.params,
        },
        sort_keys=True,
    )
    return hashlib.sha256(payload.encode()).hexdigest()


async def _get_cached(cache_key: str, ttl_hours: float = _CACHE_TTL_HOURS) -> Optional[dict[str, Any]]:
    """Return the cached output JSONB dict if a fresh record exists, otherwise None."""
    cutoff = datetime.now(timezone.utc) - timedelta(hours=ttl_hours)
    async with raw_conn() as conn:
        cur = await conn.execute(NewsRawSQL.GET_CACHED, (cache_key, cutoff))
        row = await cur.fetchone()
    return row["output"] if row else None


async def _save_to_cache(
    cache_key: str,
    query: NewsQuery,
    source: str,
    result: NewsResult,
) -> Optional[int]:
    """Persist the result to fin_markets.news_raw and return the generated row id."""
    input_payload = {
        "method": query.method,
        "symbol": query.symbol,
        "query": query.query,
        "params": query.params,
    }
    async with raw_conn() as conn:
        cur = await conn.execute(
            NewsRawSQL.INSERT_RETURNING,
            (
                query.thread_id,
                query.node_name,
                source,
                query.method,
                cache_key,
                json.dumps(input_payload),
                result.model_dump_json(),
            ),
        )
        row = await cur.fetchone()
    return row["id"] if row else None


class NewsClient:
    """Unified news client.

    Wraps yfinance, Alpha Vantage NEWS_SENTIMENT, and web-search (bing/google/
    volc/ddgs) behind a single ``fetch`` coroutine.  Results are cached in
    ``fin_markets.news_raw`` for 4 hours.

    On provider failure the client automatically retries through the fallback
    chain defined in ``_FALLBACK_CHAINS``:
      yfinance      → alpha_vantage → web_search
      alpha_vantage → yfinance      → web_search
      web_search    → alpha_vantage → yfinance
    """

    def __init__(self) -> None:
        """Initialise the client using application settings."""
        settings = get_settings()
        self._av_key: Optional[str] = settings.ALPHAVANTAGE_API_KEY

    async def _call_provider(self, source: str, query: NewsQuery) -> NewsResult:
        """Invoke a single provider by name.

        Args:
            source: One of ``'yfinance'``, ``'alpha_vantage'``, ``'web_search'``.
            query:  Structured news query.

        Returns:
            Provider result as a :class:`~app.resource_api.news_api.models.NewsResult`.

        Raises:
            ValueError: If ``alpha_vantage`` is requested but no API key is set.
        """
        if source == "yfinance":
            return await yfinance_news.fetch(query)
        if source == "alpha_vantage":
            if not self._av_key:
                raise ValueError("ALPHAVANTAGE_API_KEY is not set — skipping alpha_vantage fallback")
            return await alpha_vantage_news.fetch(query, self._av_key)  # type: ignore[arg-type]
        # web_search (ddgs / bing / google / volc depending on WEB_SEARCH_PROVIDER)
        return await web_search.fetch(query)

    async def fetch(
        self,
        query: NewsQuery,
        source: NewsSource = "yfinance",
        use_cache: bool = True,
        cache_ttl_hours: float = _CACHE_TTL_HOURS,
    ) -> tuple[NewsResult, Optional[int]]:
        """Fetch news, returning a cached result when available.

        On provider failure the client transparently retries through the
        fallback chain (see ``_FALLBACK_CHAINS``).  The first successful
        result is cached and returned regardless of which provider delivered it.

        Args:
            query: Structured query specifying method, symbol/query text, and params.
            source: Preferred provider – ``'yfinance'``, ``'alpha_vantage'``, or
                ``'web_search'``.  Actual provider may differ when fallback kicks in.
            use_cache: When ``True`` (default) a DB cache hit within ``cache_ttl_hours``
                is returned without calling any external provider.
            cache_ttl_hours: Staleness threshold in hours (default 4).  Pass ``1.0``
                for web-search sub-queries that require fresher data.

        Returns:
            A tuple of ``(NewsResult, news_raw_id)``.  ``news_raw_id`` is ``None``
            on a cache hit; it is an ``int`` when a fresh provider call was made
            and a new ``news_raw`` row was inserted.

        Raises:
            RuntimeError: If every provider in the fallback chain fails.
        """
        cache_key = _make_cache_key(source, query)

        if use_cache:
            # L1: in-memory (1-hour TTL)
            mem_hit: Optional[NewsResult] = _mem_cache.get(cache_key)
            if mem_hit is not None:
                return mem_hit, None
            # L2: database (cache_ttl_hours, default 4)
            cached = await _get_cached(cache_key, ttl_hours=cache_ttl_hours)
            if cached is not None:
                result = NewsResult.model_validate(cached)
                _mem_cache.set(cache_key, result)
                return result, None

        # Build the ordered list of providers to try: primary first, then fallbacks
        chain = [source] + _FALLBACK_CHAINS.get(source, [])
        last_exc: Exception = RuntimeError("no providers attempted")
        not_found_attempts: list[str] = []

        for provider in chain:
            try:
                result = await self._call_provider(provider, query)
            except ProviderNotFoundError as exc:
                not_found_attempts.append(exc.as_log_entry())
                logger.warning(
                    "[NewsClient] provider=%s → not found for query=%r: %s",
                    provider, query.query or query.symbol, exc,
                )
                last_exc = exc
                continue
            except Exception as exc:
                logger.warning(
                    "[NewsClient] provider=%s failed for query=%r: %s",
                    provider, query.query or query.symbol, exc,
                )
                last_exc = exc
                continue

            if provider != source:
                logger.info(
                    "[NewsClient] primary=%s failed; succeeded with fallback=%s query=%r",
                    source, provider, query.query or query.symbol,
                )
            raw_id = await _save_to_cache(cache_key, query, provider, result)
            _mem_cache.set(cache_key, result)
            # Publish to Redis Stream (best-effort, non-blocking)
            try:
                import asyncio as _asyncio
                from backend.resource_api.stream_events import publish_news_enrichment
                _asyncio.ensure_future(publish_news_enrichment(query, result, provider))
            except Exception:
                pass
            return result, raw_id

        # All providers exhausted — if every failure was "not found", return an empty
        # result with the attempt log instead of raising.
        if not_found_attempts and len(not_found_attempts) == len(chain):
            label = query.query or query.symbol or ""
            logger.warning(
                "[NewsClient] all providers returned not-found for query=%r — attempts: %s",
                label, "; ".join(not_found_attempts),
            )
            return NewsResult(
                method=query.method,
                source=source,
                symbol=query.symbol,
                query=query.query,
                not_found_attempts=not_found_attempts,
            ), None

        raise RuntimeError(
            f"All news providers failed for source={source!r} query={query.query or query.symbol!r}."
            f" Last error: {last_exc}"
        )
