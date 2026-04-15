"""Web-search provider package — dispatches to configured backend.

Backend selection via ``WEB_SEARCH_PROVIDER`` setting:
  ddgs   — DuckDuckGo (always available, no API key required)
  bing   — Bing News Search API v7 (Azure Cognitive Services, requires BING_SEARCH_API_KEY)
  google — Google Custom Search API (requires GOOGLE_CSE_API_KEY + GOOGLE_CSE_CX)
  volc   — Volcano Engine web search (requires VOLCENGINE_ACCESS_KEY_ID/SECRET)
  auto   — try bing → google → volc → ddgs; use first that is configured

The ``fetch`` coroutine below is the single public entry point and is
API-compatible with the legacy ``web_search.py`` module it replaces.
"""

from __future__ import annotations

import logging

from backend.config import get_settings
from backend.resource_api.exceptions import ProviderNotFoundError
from backend.resource_api.news_api.models import NewsQuery, NewsResult
from backend.resource_api.news_api.providers.web_search import bing, ddgs, google, volc

logger = logging.getLogger(__name__)

# Provider preference order for "auto" mode (most capable first)
_AUTO_ORDER = [bing, google, volc, ddgs]


def _pick_backend():
    """Return the backend module to use based on WEB_SEARCH_PROVIDER setting."""
    provider = get_settings().WEB_SEARCH_PROVIDER.lower()


    if provider == "volc":
        return volc
    if provider == "ddgs":
        return ddgs
    if provider == "bing":
        return bing
    if provider == "google":
        return google

    # auto: first configured provider wins; ddgs is always available as fallback
    for mod in _AUTO_ORDER[:-1]:  # skip ddgs in is_configured check
        if mod.is_configured():
            return mod
    return ddgs  # guaranteed fallback


async def fetch(query: NewsQuery) -> NewsResult:
    """Dispatch a news/web-search query to the configured backend.

    Tries the primary backend first, then falls back through available
    backends.  ``ProviderNotFoundError`` is re-raised so the outer
    ``NewsClient`` can collect it as a not-found attempt; other exceptions
    trigger the same fallback logic.

    Args:
        query: Structured news query.

    Returns:
        Normalised :class:`~app.resource_api.news_api.models.NewsResult`.
    """
    primary = _pick_backend()
    primary_name = primary.__name__.rsplit(".", 1)[-1]
    logger.info("[web_search] using backend=%s for query=%r", primary_name, query.query or query.symbol)

    not_found_attempts: list[str] = []
    all_not_found = True

    for mod in [primary, *[m for m in _AUTO_ORDER if m is not primary]]:
        if mod is not primary and hasattr(mod, "is_configured") and not mod.is_configured():
            logger.debug("[web_search] skipping unconfigured fallback backend %s", mod.__name__)
            continue
        try:
            result = await mod.fetch(query)
            backend_name = mod.__name__.rsplit(".", 1)[-1]
            if mod is not primary:
                logger.info("[web_search] fallback backend %s succeeded", backend_name)
            return result
        except ProviderNotFoundError as exc:
            not_found_attempts.append(exc.as_log_entry())
            logger.warning("[web_search/%s] → not found: %s", mod.__name__.rsplit(".", 1)[-1], exc)
        except Exception as exc:
            all_not_found = False
            logger.warning("[web_search/%s] failed: %s", mod.__name__.rsplit(".", 1)[-1], exc)

    if all_not_found and not_found_attempts:
        # Every backend said "not found" — propagate a combined ProviderNotFoundError
        # so the NewsClient can record the structured attempts list.
        raise ProviderNotFoundError(
            f"web_search/{primary_name}",
            ", ".join(not_found_attempts),
            query.symbol or query.query or "",
            "all backends returned not-found",
        )

    tried = [primary_name, *[m.__name__.rsplit(".", 1)[-1] for m in _AUTO_ORDER if m is not primary]]
    raise RuntimeError(
        f"All web-search backends failed for query={query.query!r} "
        f"(tried: {tried}). Check provider configuration and API keys."
    )
