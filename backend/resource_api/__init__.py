"""Resource API — unified market-data and news clients.

Sub-packages
------------
quant_api  — OHLCV / quote fetching with 4-hour DB cache
news_api   — news article fetching with 4-hour DB cache

Stream events
-------------
Both clients publish live-fetch results to Redis Streams after each
successful provider call.  Import helpers from this module to publish
events manually from other modules.
"""

from backend.resource_api.stream_events import publish_market_tick, publish_news_enrichment

__all__ = ["publish_market_tick", "publish_news_enrichment"]
