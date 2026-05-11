"""Mock embedding provider – deterministic, zero-dependency, 768-dim output.

Implementation split
--------------------
mock_emb.py — MockEmbeddingClient class and get_mock_embedder factory
"""

from backend.llm.providers.mock_emb.mock_emb import MockEmbeddingClient, get_mock_embedder

__all__ = ["MockEmbeddingClient", "get_mock_embedder"]
