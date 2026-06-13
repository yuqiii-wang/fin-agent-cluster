"""get_futures_stats -- placeholder for futures-specific fetch logic.

Currently the system routes futures bar fetches through
:func:`backend.langgraph.models.common_tasks.task_seqs.get_and_calculate_stats.get_stats_utils.get_ohlcv_stats.get_ohlcv_stats_handler`
because futures records are OHLCV-shaped.  This module exists as a clear
extension point for futures-specific fetch behaviour (continuous contracts,
rollover handling, expiry-specific bars, etc.) once it is needed.

Public exports
--------------
(no public handlers yet -- stub only)
"""

from __future__ import annotations

__all__: list[str] = []
