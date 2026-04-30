"""streamer — LangGraph agent package for the streaming workflow.

Exports the leaf-node function :func:`stream_runner` used by both the inner
sub-graph and re-exported at the agents level.
"""

from backend.graph.agents.streamer.node import stream_runner

__all__ = ["stream_runner"]
