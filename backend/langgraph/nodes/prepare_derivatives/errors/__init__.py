"""Error codes for prepare_derivatives node."""

from __future__ import annotations

__all__: list[str] = []

# PD-001: No stock symbol available -- query_node output missing stock_name.
# PD-002: propose_web_knowledge_urls failed -- could not construct or delegate URL for the symbol.
# PD-003: navigate_web failed -- crawl or LLM assessment error for the derivatives URL.
# PD-004: get_and_calculate_stats failed -- OHLCV fetch or indicator calculation error.
# PD-005: derivatives summary missing from agent results -- _build_final_output did not complete.
