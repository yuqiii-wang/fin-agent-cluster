"""
LLM providers for the backend.
"""

from _shared.llm.providers.base_llm import BaseLLM, normalize_spaces
from _shared.llm.providers.mock_emb import MockEmbeddingClient, get_mock_embedder
from _shared.llm.providers.mock_llm import MockLLM, get_mock_llm
from _shared.llm.providers.ollama import get_ollama_llm
from _shared.llm.providers.ark import ArkLLM, get_ark_llm

__all__ = [
    "BaseLLM",
    "normalize_spaces",
    "MockEmbeddingClient",
    "get_mock_embedder",
    "get_ollama_llm",
    "MockLLM",
    "get_mock_llm",
    "ArkLLM",
    "get_ark_llm",
]