"""EmbeddingClient protocol — common interface for all embedding providers.

Every embedding provider in ``backend.llm.providers.*_emb`` must implement
this protocol.  The factory function :func:`~backend.llm.factory.get_embedder`
returns an instance that satisfies this interface.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable


@runtime_checkable
class EmbeddingClient(Protocol):
    """Minimal embedding interface shared by all providers.

    A single method: ``embed_documents(texts) -> list[list[float]]``.
    Implementations must be callable from both sync and async contexts
    (blocking I/O must be wrapped by the implementation when needed).
    """

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        """Embed a batch of texts into float vectors.

        Args:
            texts: List of plain-text strings to embed.

        Returns:
            Parallel list of float vectors; each inner list has the same
            dimensionality as the configured model (e.g. 768).
        """
        ...


__all__ = ["EmbeddingClient"]
