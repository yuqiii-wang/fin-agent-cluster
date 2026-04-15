"""Ollama embedding provider implementation.

Provides:
- ``OllamaEmbeddingClient`` implementing ``embed_documents``
- ``probe_ollama_embedding`` health check using a greeting message
"""

from __future__ import annotations

from urllib.parse import urlparse

import httpx

from backend.config import get_settings


def _should_bypass_proxy(base_url: str) -> bool:
    """Return True when target host is local and should bypass env proxy."""
    host = (urlparse(base_url).hostname or "").lower()
    return host in {"localhost", "127.0.0.1", "::1"}


class OllamaEmbeddingClient:
    """Embedding client backed by local Ollama endpoints."""

    def __init__(self, base_url: str, model: str, timeout: float = 15.0) -> None:
        """Initialise Ollama embedding client.

        Args:
            base_url: Ollama server URL.
            model: Ollama embedding model name.
            timeout: Request timeout in seconds.
        """
        self._base_url = base_url.rstrip("/")
        self._model = model
        self._client = httpx.Client(
            trust_env=not _should_bypass_proxy(self._base_url),
            timeout=timeout,
        )

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        """Embed texts via Ollama using modern then legacy endpoint fallback."""
        if not texts:
            return []

        modern = self._client.post(
            f"{self._base_url}/api/embed",
            json={"model": self._model, "input": texts},
        )
        if modern.status_code < 400:
            payload = modern.json()
            vectors = payload.get("embeddings")
            if isinstance(vectors, list):
                return [list(map(float, v)) for v in vectors]

        vectors: list[list[float]] = []
        for text in texts:
            legacy = self._client.post(
                f"{self._base_url}/api/embeddings",
                json={"model": self._model, "prompt": text},
            )
            legacy.raise_for_status()
            embedding = legacy.json().get("embedding")
            if not isinstance(embedding, list):
                raise ValueError("Ollama /api/embeddings returned no embedding list")
            vectors.append(list(map(float, embedding)))
        return vectors


def probe_ollama_embedding(timeout: float = 10.0) -> bool:
    """Return True if Ollama can embed a greeting with configured embed model."""
    settings = get_settings()
    base = settings.OLLAMA_SERVER_URL.rstrip("/")
    greeting = "hello from health check"

    try:
        with httpx.Client(
            trust_env=not _should_bypass_proxy(base),
            timeout=timeout,
        ) as client:
            modern = client.post(
                f"{base}/api/embed",
                json={"model": settings.OLLAMA_EMBED_MODEL, "input": [greeting]},
            )
            if modern.status_code < 400:
                payload = modern.json()
                vectors = payload.get("embeddings")
                return bool(
                    isinstance(vectors, list)
                    and vectors
                    and isinstance(vectors[0], list)
                    and vectors[0]
                )

            legacy = client.post(
                f"{base}/api/embeddings",
                json={"model": settings.OLLAMA_EMBED_MODEL, "prompt": greeting},
            )
            if legacy.status_code >= 400:
                return False
            embedding = legacy.json().get("embedding")
            return bool(isinstance(embedding, list) and embedding)
    except Exception:
        return False
