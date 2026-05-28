"""Error codes for prepare_peers node."""

from __future__ import annotations

__all__: list[str] = []

# AP-001: query_node predecessor output missing or empty; stock_name/region unavailable.
# AP-002: propose_peer_stocks task failed; LLM returned invalid JSON or empty peers.
# AP-003: Target stock data fetch failed — cannot populate quant_stats for corr computation.
# AP-004: All proposed peers failed stats/corr fetch in an iteration — skipping that iteration.
# AP-005: Max iterations reached with no strongly correlated peers — using best available.
# AP-006: analyze_peer_corr task failed — no corr data available for threshold filtering.
# AP-007: peer_orchestration task failed or returned invalid action; fallback behaviour applied.
