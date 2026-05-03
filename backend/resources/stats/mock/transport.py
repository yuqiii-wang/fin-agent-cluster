"""Mock httpx transport for the stats provider.

Intercepts all requests to ``http://mock-stats/`` and returns responses
built from :mod:`backend.resources.stats.mock.stats` data.

This lets :mod:`backend.resources.stats.client` use a real ``httpx.AsyncClient``
call path — swapping to a live provider is just swapping the transport.

Provider label: ``"mock"``
"""

from __future__ import annotations

import json

import httpx

from backend.resources.stats.mock.stats import MOCK_STATS


class MockStatsTransport(httpx.AsyncBaseTransport):
    """In-process httpx transport that serves mock stats data.

    Supported routes (relative to ``http://mock-stats``):

    ``GET /stats``
        Query params: ``symbol`` (optional), ``period`` (optional), ``limit`` (default 10).
        Returns a JSON list of matching records.

    ``GET /stats/{id}``
        Returns a single record or 404.
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

        if path == "/stats":
            return self._list(params)
        if path.startswith("/stats/"):
            record_id = path[len("/stats/"):]
            return self._get(record_id)
        return httpx.Response(404, json={"detail": "not found"})

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _list(self, params: dict[str, str]) -> httpx.Response:
        symbol = params.get("symbol")
        period = params.get("period")
        limit = int(params.get("limit", 10))
        rows = MOCK_STATS
        if symbol:
            upper = symbol.upper()
            rows = [r for r in rows if r["symbol"] == upper]
        if period:
            rows = [r for r in rows if r["period"] == period]
        return httpx.Response(200, content=json.dumps(rows[:limit]).encode())

    def _get(self, record_id: str) -> httpx.Response:
        for row in MOCK_STATS:
            if row["id"] == record_id:
                return httpx.Response(200, content=json.dumps(row).encode())
        return httpx.Response(404, json={"detail": "STATS_NOT_FOUND"})
