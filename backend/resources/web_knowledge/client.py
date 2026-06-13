"""Web-knowledge HTTP client.

Fetches the raw HTML of a known financial web page (competitors, press releases,
option chain) for a given equity symbol by performing a plain HTTP GET request.

Usage::

    from backend.resources.web_knowledge.client import WebKnowledgeClient
    from backend.resources.web_knowledge.models import WebPageType

    client = WebKnowledgeClient()
    response = await client.fetch("AAPL", WebPageType.competitors, exchange="NASDAQ")
    print(response.url)
    print(response.html[:500])
    await client.aclose()
"""

from __future__ import annotations

import logging

from backend.config import get_settings
from _shared.httpx_client import HTTPStatusError, RequestError, make_web_browser_async_client
from backend.resources.web_knowledge.errors import WK_EMPTY_RESPONSE, WK_FETCH_FAILED
from backend.resources.web_knowledge.models import WebPageResponse, WebPageType
from backend.resources.web_knowledge.urls import build_url

logger = logging.getLogger(__name__)

_TIMEOUT_SECONDS = 30.0


class WebKnowledgeClient:
    """Async HTTP client for web-knowledge page fetches.

    Attributes:
        _http: Shared :class:`~backend.httpx_client.AsyncClient` instance.
    """

    def __init__(self) -> None:
        """Initialise the client, wiring in proxy settings from config."""
        self._http = make_web_browser_async_client()

    async def fetch(
        self,
        symbol: str,
        page_type: WebPageType,
        exchange: str | None = None,
    ) -> WebPageResponse:
        """Fetch the HTML for the given symbol and page type.

        Args:
            symbol:    Equity ticker symbol, e.g. ``'AAPL'``.
            page_type: Category of page to retrieve.
            exchange:  Exchange the symbol is listed on (required for
                       ``competitors``), e.g. ``'NASDAQ'``.

        Returns:
            :class:`~backend.resources.web_knowledge.models.WebPageResponse`
            with the raw HTML and resolved URL.

        Raises:
            ValueError:  When *exchange* is required but not supplied.
            RuntimeError: When the HTTP fetch fails or the response body is empty.
        """
        url = build_url(page_type, symbol, exchange)
        try:
            response = await self._http.get(url)
            response.raise_for_status()
        except HTTPStatusError as exc:
            logger.error(
                "[%s] HTTP %s fetching %s: %s",
                WK_FETCH_FAILED,
                exc.response.status_code,
                url,
                exc,
            )
            raise RuntimeError(
                f"[{WK_FETCH_FAILED}] HTTP {exc.response.status_code} fetching {url}"
            ) from exc
        except RequestError as exc:
            logger.error("[%s] Network error fetching %s: %s", WK_FETCH_FAILED, url, exc)
            raise RuntimeError(f"[{WK_FETCH_FAILED}] Network error fetching {url}: {exc}") from exc

        html = response.text
        if not html.strip():
            logger.error("[%s] Empty response body from %s", WK_EMPTY_RESPONSE, url)
            raise RuntimeError(f"[{WK_EMPTY_RESPONSE}] Empty response body from {url}")

        return WebPageResponse(
            symbol=symbol.upper(),
            exchange=exchange.upper() if exchange else None,
            page_type=page_type,
            url=url,
            html=html,
        )

    async def aclose(self) -> None:
        """Close the underlying HTTP client."""
        await self._http.aclose()
