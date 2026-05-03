"""Mock httpx transport for the news provider.

Intercepts all requests to ``http://mock-news/`` and returns responses
built from :mod:`backend.resources.news.mock.text` data.

This lets :mod:`backend.resources.news.client` use a real ``httpx.AsyncClient``
call path — swapping to a live provider is just swapping the transport.

Provider label: ``"mock"``
"""

from __future__ import annotations

import json
from datetime import datetime, timezone

import httpx

from backend.resources.news.mock.text import MOCK_NEWS


def _serialise(obj: object) -> str:
    """JSON-serialise objects that include ``datetime`` values."""
    if isinstance(obj, datetime):
        return obj.isoformat()
    raise TypeError(f"Not serialisable: {type(obj)}")


class MockNewsTransport(httpx.AsyncBaseTransport):
    """In-process httpx transport that serves mock news data.

    Supported routes (relative to ``http://mock-news``):

    ``GET /news``
        Query params: ``symbol`` (optional), ``limit`` (default 10).
        Returns a JSON list of matching articles.

    ``GET /news/{id}``
        Returns a single article or 404.
    """

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        """Dispatch the request to the appropriate mock handler.

        Args:
            request: The outgoing httpx Request object.

        Returns:
            An httpx.Response with JSON body.
        """
        path = request.url.path.rstrip("/")
        params = dict(request.url.params)

        if path == "/news":
            return self._list(params)
        if path.startswith("/news/"):
            article_id = path[len("/news/"):]
            return self._get(article_id)
        return httpx.Response(404, json={"detail": "not found"})

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _list(self, params: dict[str, str]) -> httpx.Response:
        symbol = params.get("symbol")
        limit = int(params.get("limit", 10))
        rows = MOCK_NEWS
        if symbol:
            upper = symbol.upper()
            rows = [r for r in rows if r["symbol"] == upper]
        payload = [_article_dict(r) for r in rows[:limit]]
        return httpx.Response(200, content=json.dumps(payload, default=_serialise).encode())

    def _get(self, article_id: str) -> httpx.Response:
        for row in MOCK_NEWS:
            if row["id"] == article_id:
                return httpx.Response(
                    200,
                    content=json.dumps(_article_dict(row), default=_serialise).encode(),
                )
        return httpx.Response(404, json={"detail": "NEWS_NOT_FOUND"})


def _article_dict(row: dict) -> dict:
    """Normalise a mock row into a serialisable dict."""
    result = dict(row)
    if isinstance(result.get("published_at"), datetime):
        result["published_at"] = result["published_at"].isoformat()
    return result
