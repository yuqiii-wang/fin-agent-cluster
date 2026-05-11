"""Mock embedding provider – deterministic, zero-dependency, 768-dim output.

Encoding strategy
-----------------
Given a text ``msg``:

1. Split into words: ``words = msg.split()``
2. Accumulate per-character and per-word statistics:

   * ``char_freq[256]``  – ASCII byte frequency histogram (normalised by
     total character count across all words)
   * ``word_lengths``    – list of individual word lengths

3. Derive aggregate word-length stats: ``n``, ``mean``, ``max``.

4. Build a 768-dim float vector from those statistics:

   * dims  [0  …255] – normalised char-frequency histogram
   * dims  [256…511] – histogram rotated by 128 (adds positional variety)
   * dims  [512…767] – word-length cosine scatter:
     ``val = (wl / max_len) * cos(i * mean_len / max_len)``

5. L2-normalise to unit length so cosine similarity is well-defined.
"""

from __future__ import annotations

import math

_DIM = 768


class MockEmbeddingClient:
    """Deterministic mock embedder; always returns 768-dim unit vectors.

    Satisfies the ``EmbeddingClient`` protocol (``embed_documents``).
    """

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return [self._embed_one(t) for t in texts]

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _embed_one(self, text: str) -> list[float]:
        words = text.split()
        if not words:
            return [0.0] * _DIM

        # ── stat pass ─────────────────────────────────────────────────
        char_freq: list[int] = [0] * 256
        word_lengths: list[int] = []

        for word in words:
            word_lengths.append(len(word))
            for ch in word:
                char_freq[ord(ch) & 0xFF] += 1

        total_chars: int = sum(char_freq) or 1
        cf: list[float] = [c / total_chars for c in char_freq]  # 256 normalised

        n: int = len(word_lengths)
        mean_len: float = sum(word_lengths) / n
        max_len: float = float(max(word_lengths)) or 1.0

        # ── mapping to 768 dims ────────────────────────────────────────
        # [0..255]   char freq histogram
        vec: list[float] = cf[:]

        # [256..511] rotated histogram (128-position circular shift)
        vec += cf[128:] + cf[:128]

        # [512..767] cosine scatter keyed by word lengths
        for i in range(256):
            wl: float = float(word_lengths[i % n])
            val: float = (wl / max_len) * math.cos(i * mean_len / max_len)
            vec.append(val)

        # ── L2-normalise ───────────────────────────────────────────────
        norm: float = math.sqrt(sum(v * v for v in vec)) or 1.0
        return [v / norm for v in vec]


def get_mock_embedder() -> MockEmbeddingClient:
    """Return a shared ``MockEmbeddingClient`` instance."""
    return MockEmbeddingClient()


__all__ = ["MockEmbeddingClient", "get_mock_embedder"]
