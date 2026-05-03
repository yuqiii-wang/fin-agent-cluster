"""E2E test fixtures — deterministic JSON responses for ``"DO E2E TEST NOW"`` queries.

These fixtures are the single source of truth for the mock E2E test pipeline.
The query fixture drives ``E2EMockChatModel``; the news/stats fixtures live in
their respective ``resources/*/mock/`` modules and share the ``"TEST"`` symbol.
"""

from __future__ import annotations

#: Trigger prefix recognised by :class:`E2EMockChatModel`.
E2E_TRIGGER: str = "DO E2E TEST NOW"

#: Deterministic query-parse response returned by :class:`E2EMockChatModel`.
#: Shape must match :class:`~backend.graph.agents._shared.nodes.query_node.tasks.analyze_user_query.models.QueryTaskOutput`.
E2E_QUERY_RESPONSE: dict = {
    "symbol": "AAPL",
    "rationale": "E2E automated testing.",
    "industry": "Technology",
    "peers": ["MSFT", "GOOGL"],
    "opposite_industry": "",
    "opposite_industry_peers": [],
}

__all__ = ["E2E_TRIGGER", "E2E_QUERY_RESPONSE"]
