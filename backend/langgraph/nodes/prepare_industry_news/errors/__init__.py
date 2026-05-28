"""Error codes for prepare_industry_news node."""

from __future__ import annotations

__all__: list[str] = []

# PIN-001: query_node output unavailable — could not resolve stock_name; news will run topic-only.
# PIN-002: propose_industry_news_topics failed — LLM topic proposal raised; falling back to symbol-only get_news.
