"""Tasks package for prepare_peers node."""

from backend.langgraph.nodes.prepare_peers.tasks.analyze_peer_corr import (
    analyze_peer_corr,
    AnalyzePeerCorrInput,
    AnalyzePeerCorrOutput,
)
from backend.langgraph.nodes.prepare_peers.tasks.peer_orchestration import (
    peer_orchestration,
    PeerOrchestrationInput,
    PeerOrchestrationOutput,
    TopCorrPeer,
    STREAM_PROMPT_BUILDERS as _PORCH_BUILDERS,
)
from backend.langgraph.nodes.prepare_peers.tasks.propose_peer_urls import (
    propose_peer_urls,
    STREAM_PROMPT_BUILDERS as _PPU_BUILDERS,
)

STREAM_PROMPT_BUILDERS: dict = {**_PPU_BUILDERS, **_PORCH_BUILDERS}

__all__ = [
    "propose_peer_urls",
    "analyze_peer_corr",
    "AnalyzePeerCorrInput",
    "AnalyzePeerCorrOutput",
    "peer_orchestration",
    "PeerOrchestrationInput",
    "PeerOrchestrationOutput",
    "TopCorrPeer",
    "STREAM_PROMPT_BUILDERS",
]
