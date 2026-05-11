"""MockEmbeddingClient — deterministic, zero-dependency, 768-dim embedder."""

from __future__ import annotations

import math

_DIM = 768


class MockEmbeddingClient:
    """Deterministic mock embedder; always returns 768-dim unit vectors.

    Satisfies the ``EmbeddingClient`` protocol (``embed_documents``).

    Encoding strategy
    -----------------
    Given a text ``msg``:

    1. Split into words and accumulate per-character/per-word statistics.
    2. Build a 768-dim float vector:

       * dims  [0  …255] – normalised char-frequency histogram
       * dims  [256…511] – histogram rotated by 128
       * dims  [512…767] – word-length cosine scatter

    3. L2-normalise to unit length.
    """

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        """Embed a list of texts into 768-dim unit vectors."""
        return [self._embed_one(t) for t in texts]

    def _embed_one(self, text: str) -> list[float]:
        words = text.split()
        if not words:
            return [0.0] * _DIM

        char_freq: list[int] = [0] * 256
        word_lengths: list[int] = []

        for word in words:
            word_lengths.append(len(word))
            for ch in word:
                char_freq[ord(ch) & 0xFF] += 1

        total_chars: int = sum(char_freq) or 1
        cf: list[float] = [c / total_chars for c in char_freq]

        n: int = len(word_lengths)
        mean_len: float = sum(word_lengths) / n
        max_len: float = float(max(word_lengths)) or 1.0

        vec: list[float] = cf[:]
        vec += cf[128:] + cf[:128]

        for i in range(256):
            wl: float = float(word_lengths[i % n])
            val: float = (wl / max_len) * math.cos(i * mean_len / max_len)
            vec.append(val)

        norm: float = math.sqrt(sum(v * v for v in vec)) or 1.0
        return [v / norm for v in vec]


def get_mock_embedder() -> MockEmbeddingClient:
    """Return a shared ``MockEmbeddingClient`` instance."""
    return MockEmbeddingClient()


__all__ = ["MockEmbeddingClient", "get_mock_embedder"]
