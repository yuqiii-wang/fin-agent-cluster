"""News provider client.

Fetches news articles via httpx.  In mock mode (default when no real
provider URL is configured) requests are handled in-process by
:class:`~backend.resources.news.mock.transport.MockNewsTransport`.

Provider label: ``"mock"`` (set on :attr:`NewsClient.provider`).

Usage::

    from backend.resources.news.client import NewsClient

    client = NewsClient()                       # uses mock transport
    articles = await client.list_news("AAPL")
    article  = await client.get_news("news-aapl-001")
"""

from __future__ import annotations

import logging

import httpx

from backend.resources.news.mock.transport import MockNewsTransport
from backend.resources.news.models import NewsArticle, NewsListResponse

logger = logging.getLogger(__name__)

_MOCK_BASE_URL = "http://mock-news"


class NewsClient:
    """Async news provider client backed by a configurable httpx transport.

    Attributes:
        provider: Short identifier for the active provider, e.g. ``"mock"``.
    """

    provider: str = "mock"

    def __init__(self) -> None:
        """Initialise with the mock transport."""
        self._http = httpx.AsyncClient(
            base_url=_MOCK_BASE_URL,
            transport=MockNewsTransport(),
        )

    async def list_news(
        self,
        symbol: str | None = None,
        limit: int = 10,
    ) -> NewsListResponse:
        """Fetch a list of news articles, optionally filtered by symbol.

        Args:
            symbol: Equity ticker to filter on, or ``None`` for all.
            limit:  Maximum number of articles to return.

        Returns:
            :class:`~backend.resources.news.models.NewsListResponse`.
        """
        params: dict[str, str | int] = {"limit": limit}
        if symbol is not None:
            params["symbol"] = symbol

        logger.debug("news.list_news provider=%s symbol=%s limit=%d", self.provider, symbol, limit)
        response = await self._http.get("/news", params=params)
        if not response.is_success:
            raise ValueError(
                f"news.list_news failed: status={response.status_code} body={response.text[:500]!r}"
            )
        items = [NewsArticle.model_validate(row) for row in response.json()]
        return NewsListResponse(items=items, total=len(items))

    async def get_news(self, article_id: str) -> NewsArticle | None:
        """Fetch a single news article by ID.

        Args:
            article_id: Unique article identifier.

        Returns:
            :class:`~backend.resources.news.models.NewsArticle`, or ``None`` if not found.
        """
        logger.debug("news.get_news provider=%s id=%s", self.provider, article_id)
        response = await self._http.get(f"/news/{article_id}")
        if response.status_code == 404:
            return None
        if not response.is_success:
            raise ValueError(
                f"news.get_news failed: status={response.status_code} body={response.text[:500]!r}"
            )
        return NewsArticle.model_validate(response.json())

    async def aclose(self) -> None:
        """Close the underlying httpx client."""
        await self._http.aclose()
