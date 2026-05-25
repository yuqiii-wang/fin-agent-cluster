"""Ollama embedding provider."""

from backend.llm.providers.ollama_emb.ollama_emb import OllamaEmbeddingClient, get_ollama_embedder

__all__ = ["OllamaEmbeddingClient", "get_ollama_embedder"]
