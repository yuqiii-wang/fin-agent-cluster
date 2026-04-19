"""Unified quant market-data client with 4-hour DB-backed cache."""

from __future__ import annotations

import hashlib
import json
import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from backend.config import get_settings
from backend.db import raw_conn
from backend.db.postgres.queries.fin_markets_quant import QuantRawSQL
from backend.resource_api.exceptions import ProviderNotFoundError
from backend.resource_api.mem_cache import TimedLRUCache
from backend.resource_api.quant_api.configs.sources import QUANT_SOURCE_DEFAULTS
from backend.resource_api.quant_api.models import QuantQuery, QuantResult, QuantSource
from backend.resource_api.quant_api.providers import (
    alpha_vantage,
    akshare_provider,
    datareader_provider,
    fmp_provider,
    fred_provider,
    yfinance_provider,
)

logger = logging.getLogger(__name__)

# Provider-specific ticker translation maps — imported once at module load.
_TICKER_MAPS: dict[str, dict[str, str | None]] = {
    "yfinance":      yfinance_provider.TICKER_MAP,
    "datareader":    datareader_provider.TICKER_MAP,
    "alpha_vantage": alpha_vantage.TICKER_MAP,
    "akshare":       akshare_provider.TICKER_MAP,
    "fred":          fred_provider.TICKER_MAP,
    "fmp":           fmp_provider.TICKER_MAP,
}


def translate_symbol(symbol: str, provider: str) -> str | None:
    """Translate a canonical ticker symbol to the format expected by ``provider``.

    Looks up ``symbol`` in the provider's ``TICKER_MAP``.  If the symbol is
    explicitly mapped to ``None`` the provider cannot serve it; the caller
    should skip this provider.  If the symbol is not in the map at all it is
    returned unchanged (pass-through).

    Args:
        symbol:   Canonical ticker symbol, e.g. ``'GC=F'``, ``'^GSPC'``.
        provider: Provider name string, e.g. ``'yfinance'``, ``'datareader'``.

    Returns:
        Translated symbol string, or ``None`` when the provider cannot fetch it.
    """
    mapping = _TICKER_MAPS.get(provider, {})
    if symbol in mapping:
        return mapping[symbol]   # may be None → provider does not support it
    return symbol                # not in map → pass through unchanged

_CACHE_TTL_HOURS = 4
# L1: in-memory cache — 1-hour TTL, evicted before the 4-hour DB cache expires.
_mem_cache: TimedLRUCache = TimedLRUCache()

# Fallback order when the requested source fails.
# Key = primary source; value = ordered list of sources to try next.
# akshare → alpha_vantage → yfinance for CN; yfinance is always last resort.
_FALLBACK_CHAINS: dict[str, list[str]] = {
    "akshare":       ["alpha_vantage", "datareader", "fred", "yfinance"],
    "yfinance":      [],  # last resort — no further fallback
    "datareader":    ["alpha_vantage", "fred", "yfinance"],
    "alpha_vantage": ["datareader", "fred", "yfinance"],
    "fred":          ["datareader", "yfinance"],
    "fmp":           ["alpha_vantage", "datareader", "fred", "yfinance"],
}


def _make_cache_key(source: str, query: QuantQuery) -> str:
    """Produce a deterministic sha256 cache key for the given source + query."""
    payload = json.dumps(
        {"source": source, "method": query.method, "symbol": query.symbol.upper(), "params": query.params},
        sort_keys=True,
    )
    return hashlib.sha256(payload.encode()).hexdigest()


async def _get_cached(cache_key: str) -> Optional[dict[str, Any]]:
    """Return the cached output JSONB dict if a fresh record exists, otherwise None."""
    cutoff = datetime.now(timezone.utc) - timedelta(hours=_CACHE_TTL_HOURS)
    async with raw_conn() as conn:
        cur = await conn.execute(QuantRawSQL.GET_CACHED, (cache_key, cutoff))
        row = await cur.fetchone()
    return row["output"] if row else None


async def _save_to_cache(
    cache_key: str,
    query: QuantQuery,
    source: str,
    result: QuantResult,
) -> None:
    """Persist the result to fin_markets.quant_raw."""
    async with raw_conn() as conn:
        await conn.execute(
            QuantRawSQL.INSERT,
            (
                query.thread_id,
                query.node_name,
                source,
                query.method,
                query.symbol.upper(),
                cache_key,
                json.dumps({"symbol": query.symbol, "params": query.params}),
                result.model_dump_json(),
            ),
        )


class QuantClient:
    """Unified market-data client supporting yfinance, Alpha Vantage, and AKShare.

    Provider selection follows the country-based priority defined in
    :class:`~backend.config.Settings`:
      - China (region='cn'):  akshare → alpha_vantage → yfinance
      - US   (region='us'):   alpha_vantage → yfinance
      - Others / fallback:    yfinance

    Pass ``source='auto'`` (default) to activate the region-aware logic, or
    specify a concrete provider name to override it.

    Results are cached in ``fin_markets.quant_raw`` for 4 hours.
    """

    def __init__(self) -> None:
        """Initialise the client using application settings."""
        settings = get_settings()
        self._av_key: Optional[str] = settings.ALPHAVANTAGE_API_KEY
        self._fmp_key: Optional[str] = settings.FMP_API_KEY
        self._fmp_base_url: str = settings.FMP_BASE_URL
        # Ordered provider lists keyed by region code (lower-case).
        # Built once from settings so callers don't need to know the config shape.
        self._region_sources: dict[str, list[str]] = _build_region_source_map(settings)

    def resolve_primary(self, region: Optional[str] = None) -> str:
        """Return the preferred primary provider name for a given region.

        Args:
            region: fin_markets.regions code (e.g. ``'cn'``, ``'us'``), or
                    ``None`` to use the global fallback.

        Returns:
            Provider name string.
        """
        if region:
            chain = self._region_sources.get(region.lower())
            if chain:
                return chain[0]
        return self._region_sources.get("default", ["yfinance"])[0]

    def resolve_chain(self, region: Optional[str] = None) -> list[str]:
        """Return the full ordered provider chain for a given region.

        Args:
            region: fin_markets.regions code, or ``None`` for default.

        Returns:
            Ordered list of provider name strings to try in sequence.
        """
        if region:
            chain = self._region_sources.get(region.lower())
            if chain:
                return list(chain)
        return list(self._region_sources.get("default", ["yfinance"]))

    async def _call_provider(self, source: str, query: QuantQuery) -> QuantResult:
        """Invoke a single provider by name, translating the symbol first.

        Looks up the canonical ``query.symbol`` in the provider's ``TICKER_MAP``
        and rewrites the query with the translated symbol before dispatching.
        If the translation returns ``None`` the provider explicitly does not
        support this ticker, and a :class:`ProviderNotFoundError` is raised so
        the client falls through to the next provider.

        Args:
            source: One of ``'yfinance'``, ``'alpha_vantage'``, ``'akshare'``,
                    or ``'datareader'``.
            query:  Structured market-data query.

        Returns:
            Provider result as a :class:`QuantResult`.

        Raises:
            ProviderNotFoundError: When the provider's TICKER_MAP marks the
                ticker as unsupported (mapped to ``None``).
            ValueError: If a provider is requested but not configured.
        """
        translated = translate_symbol(query.symbol, source)
        if translated is None:
            raise ProviderNotFoundError(
                source, query.method, query.symbol,
                f"ticker '{query.symbol}' is not supported by provider '{source}' (TICKER_MAP → None)",
            )
        # Rewrite query with the provider-specific symbol when it differs
        if translated != query.symbol:
            query = query.model_copy(update={"symbol": translated})

        if source == "alpha_vantage":
            if not self._av_key:
                raise ValueError("ALPHAVANTAGE_API_KEY is not set — skipping alpha_vantage")
            return await alpha_vantage.fetch(query, self._av_key)  # type: ignore[arg-type]
        if source == "fmp":
            if not self._fmp_key:
                raise ValueError("FMP_API_KEY is not set — skipping fmp")
            return await fmp_provider.fetch(query, self._fmp_base_url, self._fmp_key)
        if source == "akshare":
            return await akshare_provider.fetch(query)
        if source == "datareader":
            return await datareader_provider.fetch(query)
        if source == "fred":
            return await fred_provider.fetch(query)
        return await yfinance_provider.fetch(query)

    async def fetch(
        self,
        query: QuantQuery,
        source: QuantSource = "auto",
        use_cache: bool = True,
        region: Optional[str] = None,
    ) -> QuantResult:
        """Fetch market data, returning a cached result when available.

        When ``source='auto'`` the client selects the primary provider based on
        ``region`` (via :meth:`resolve_primary`) and walks the fallback chain on
        failure.  Pass an explicit provider name to bypass region logic.

        Args:
            query:     Structured query specifying symbol, method, and params.
            source:    ``'auto'`` (default), ``'akshare'``, ``'alpha_vantage'``, or ``'yfinance'``.
            use_cache: When ``True`` (default) a DB cache hit within 4 hours
                       is returned without calling the external API.
            region:    fin_markets.regions code used for provider selection when
                       ``source='auto'`` (e.g. ``'cn'``, ``'us'``).

        Returns:
            A normalised :class:`QuantResult`.

        Raises:
            RuntimeError: If every provider in the fallback chain fails.
        """
        if source == "auto":
            chain = self.resolve_chain(region)
            primary = chain[0]
        else:
            primary = source
            chain = [primary] + _FALLBACK_CHAINS.get(primary, [])

        cache_key = _make_cache_key(primary, query)
        if use_cache:
            # L1: in-memory (1-hour TTL)
            mem_hit: Optional[QuantResult] = _mem_cache.get(cache_key)
            if mem_hit is not None:
                return mem_hit
            # L2: database (4-hour TTL)
            try:
                cached = await _get_cached(cache_key)
                if cached is not None:
                    result = QuantResult.model_validate(cached)
                    _mem_cache.set(cache_key, result)
                    return result
            except Exception:
                pass  # cache miss on DB error — proceed to live fetch

        last_exc: Exception = RuntimeError("no providers attempted")
        not_found_attempts: list[str] = []

        for provider in chain:
            try:
                result = await self._call_provider(provider, query)
                if provider != primary:
                    logger.info(
                        "[QuantClient] primary=%s failed; succeeded with fallback=%s symbol=%s method=%s",
                        primary, provider, query.symbol, query.method,
                    )
                try:
                    await _save_to_cache(cache_key, query, provider, result)
                except Exception:
                    pass  # cache write failure is non-fatal
                _mem_cache.set(cache_key, result)
                # Publish to Redis Stream (best-effort, non-blocking)
                try:
                    import asyncio as _asyncio
                    from backend.resource_api.stream_events import publish_market_tick
                    _asyncio.ensure_future(publish_market_tick(query, result, provider))
                except Exception:
                    pass
                return result
            except ProviderNotFoundError as exc:
                not_found_attempts.append(exc.as_log_entry())
                logger.warning(
                    "[QuantClient] provider=%s → not found for symbol=%s method=%s: %s",
                    provider, query.symbol, query.method, exc,
                )
                last_exc = exc
            except Exception as exc:
                logger.warning(
                    "[QuantClient] provider=%s failed for symbol=%s method=%s: %s",
                    provider, query.symbol, query.method, exc,
                )
                last_exc = exc

        # All providers exhausted — if every failure was "not found", return an empty result
        if not_found_attempts and len(not_found_attempts) == len(chain):
            logger.warning(
                "[QuantClient] all providers returned not-found for symbol=%s method=%s — attempts: %s",
                query.symbol, query.method, "; ".join(not_found_attempts),
            )
            return QuantResult(
                symbol=query.symbol.upper(),
                method=query.method,
                source=primary,  # type: ignore[arg-type]
                not_found_attempts=not_found_attempts,
            )

        raise RuntimeError(
            f"All quant providers failed for region={region!r} symbol={query.symbol!r}"
            f" method={query.method!r}. Last error: {last_exc}"
        )


# ---------------------------------------------------------------------------
# Region-to-provider map builder
# ---------------------------------------------------------------------------

def _build_region_source_map(settings: Any) -> dict[str, list[str]]:
    """Construct the region → ordered provider list mapping from settings.

    Reads ``QUANT_SOURCES_*`` env overrides from settings; falls back to the
    defaults defined in :data:`~backend.resource_api.quant_api.constants.QUANT_SOURCE_DEFAULTS`.

    Args:
        settings: Application :class:`~backend.config.Settings` instance.

    Returns:
        Dict mapping region codes (lower-case) and ``'default'`` to ordered
        provider name lists.
    """
    def _parse(attr: str, region_key: str) -> list[str]:
        """Return env-override list when set, otherwise the constant default."""
        raw: str = getattr(settings, attr, "") or ""
        if raw.strip():
            return [s.strip() for s in raw.split(",") if s.strip()]
        return list(QUANT_SOURCE_DEFAULTS.get(region_key, QUANT_SOURCE_DEFAULTS["default"]))

    return {
        "cn":      _parse("QUANT_SOURCES_CN",      "cn"),
        "hk":      _parse("QUANT_SOURCES_HK",      "hk"),
        "us":      _parse("QUANT_SOURCES_US",       "us"),
        "tw":      _parse("QUANT_SOURCES_TW",       "tw"),
        "macro":   _parse("QUANT_SOURCES_MACRO",    "macro"),
        "default": _parse("QUANT_SOURCES_DEFAULT",  "default"),
    }


def _make_cache_key(source: str, query: QuantQuery) -> str:
    """Produce a deterministic sha256 cache key for the given source + query."""
    payload = json.dumps(
        {"source": source, "method": query.method, "symbol": query.symbol.upper(), "params": query.params},
        sort_keys=True,
    )
    return hashlib.sha256(payload.encode()).hexdigest()


async def _get_cached(cache_key: str) -> Optional[dict[str, Any]]:
    """Return the cached output JSONB dict if a fresh record exists, otherwise None."""
    cutoff = datetime.now(timezone.utc) - timedelta(hours=_CACHE_TTL_HOURS)
    async with raw_conn() as conn:
        cur = await conn.execute(QuantRawSQL.GET_CACHED, (cache_key, cutoff))
        row = await cur.fetchone()
    return row["output"] if row else None


async def _save_to_cache(
    cache_key: str,
    query: QuantQuery,
    source: str,
    result: QuantResult,
) -> None:
    """Persist the result to fin_markets.quant_raw."""
    async with raw_conn() as conn:
        await conn.execute(
            QuantRawSQL.INSERT,
            (
                query.thread_id,
                query.node_name,
                source,
                query.method,
                query.symbol.upper(),
                cache_key,
                json.dumps({"symbol": query.symbol, "params": query.params}),
                result.model_dump_json(),
            ),
        )
