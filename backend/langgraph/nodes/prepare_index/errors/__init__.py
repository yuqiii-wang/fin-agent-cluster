"""Error codes for prepare_index node."""

from __future__ import annotations

__all__: list[str] = []

# AI-001: No market-index instruments loaded from DB — macro_instruments table empty or query failed.
# AI-002: All macro market-index instruments failed stats fetch — get_and_calculate_stats errored for every symbol.
# AI-003: Partial macro instruments failure — one or more macro symbols failed stats fetch; others succeeded.
# AI-004: propose_index returned no equity indexes — market_indexes cache empty or all codes missing.
# AI-005: Equity index stats failed for a specific index — get_and_calculate_stats errored for that ticker.
# AI-006: All equity index stats failed — get_and_calculate_stats errored for every proposed index ticker.
