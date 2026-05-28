"""global_state.py — Cross-iteration agent state for prepare_peers."""

from __future__ import annotations

from dataclasses import dataclass, field

from backend.langgraph.models.node_utils.agent_step_mixin import AgentGlobalStateBase


@dataclass
class AgentGlobalState(AgentGlobalStateBase):
    """Mutable state that persists across all loop iterations.

    Extends :class:`~backend.langgraph.models.node_utils.agent_step_mixin.AgentGlobalStateBase`
    with prepare_peers-specific fields.

    Attributes:
        target:               Target stock ticker (uppercased).
        excluded_urls:        URLs already attempted; ``propose_url`` excludes these.
        excluded_peers:       Peer tickers already processed (confirmed or rejected).
        all_peer_corr:        Best abs-corr score seen per peer symbol.
        all_confirmed:        All confirmed peers (may have duplicates; deduped at final selection).
        all_corr_detail:      Detailed corr breakdown per peer (best seen per symbol).
        df_split_map:         OHLCV DataFrame split per symbol (target + validated peers).
        last_proposed_url:    URL from the most recent ``propose_url`` step; provides
                              continuity when a later step restarts without ``propose_url``.
        target_stats_fetched: True once the target's stats have been fetched.
        industry:             Industry string extracted from the sandbox JSON.
    """

    target: str = ""
    excluded_urls: list[str] = field(default_factory=list)
    excluded_peers: list[str] = field(default_factory=list)
    all_peer_corr: dict[str, float] = field(default_factory=dict)
    all_confirmed: list[str] = field(default_factory=list)
    all_corr_detail: dict[str, dict] = field(default_factory=dict)
    df_split_map: dict[str, dict] = field(default_factory=dict)
    last_proposed_url: str = ""
    target_stats_fetched: bool = False
    industry: str = ""


__all__ = ["AgentGlobalState"]
