"""
Unified LLM interface for the backend.
The Interface is a dict that by what key to get the LLM provider.
"""

from backend.llm.embedding import EmbeddingClient
from backend.llm.factory import EmbeddingProvider, LLMProvider, get_embedder, get_llm

__all__ = ["EmbeddingClient", "EmbeddingProvider", "LLMProvider", "get_embedder", "get_llm"]

