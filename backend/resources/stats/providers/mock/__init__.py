"""Mock stats data for the stats provider.

Exports
-------
MOCK_STATS : list[dict]
    List of mock stats record dicts compatible with
    :class:`~backend.resources.stats.models.StatsRecord`.
"""

from __future__ import annotations

from backend.resources.stats.providers.mock.stats import MOCK_STATS

__all__ = ["MOCK_STATS"]
