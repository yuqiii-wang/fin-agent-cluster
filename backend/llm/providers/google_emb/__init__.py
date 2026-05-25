"""Google text-embedding-004 provider."""

from backend.llm.providers.google_emb.google_emb import GoogleEmbeddingClient, get_google_embedder

__all__ = ["GoogleEmbeddingClient", "get_google_embedder"]
