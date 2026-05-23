"""Tasks package for prepare_peers node."""

from backend.langgraph.nodes.prepare_peers.tasks.analyze_peer_corr import (
    analyze_peer_corr,
    AnalyzePeerCorrInput,
    AnalyzePeerCorrOutput,
)
from backend.langgraph.nodes.prepare_peers.tasks.propose_peer_stocks import (
    propose_peer_stocks,
    STREAM_PROMPT_BUILDERS as _PPS_BUILDERS,
)

STREAM_PROMPT_BUILDERS: dict = {**_PPS_BUILDERS}

__all__ = [
    "propose_peer_stocks",
    "analyze_peer_corr",
    "AnalyzePeerCorrInput",
    "AnalyzePeerCorrOutput",
    "STREAM_PROMPT_BUILDERS",
]
