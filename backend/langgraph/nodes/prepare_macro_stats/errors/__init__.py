"""Error codes for analyze_economics node."""

from __future__ import annotations

__all__: list[str] = []

# AE-001: No macro instruments loaded from DB — macro_instruments table empty or query failed.
# AE-002: All instruments failed stats fetch — get_and_calculate_stats returned errors for every symbol.
# AE-003: Partial instruments failure — one or more symbols failed stats fetch; others succeeded.
