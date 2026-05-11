"""Mock LLM provider for throughput and concurrency testing.

Token sequence
--------------
Every stream emits exactly the following tokens in order::

    "<think>"
    … body tokens …
    "</think>"
    JSON summary  ← key depends on mode (see below)

Modes
-----
``fanout``
    Emit all body tokens as fast as possible (``await asyncio.sleep(0)``
    between yields).  Use when you want to saturate throughput, e.g. with
    ``total_tokens=1_000_000``.

``throttle``
    Emit body tokens at a steady ``tokens_per_sec`` rate (default 100).
    Uses absolute timestamps to avoid drift accumulation.

``semantic``
    Emit AAPL-related noun/verb/adjective combinations at exactly
    30 tokens/sec for 10 seconds (300 tokens total).

Implementation split
--------------------
word_pool.py — AAPL word pools and token pool builder
mock_llm.py  — MockLLM class and get_mock_llm factory
"""

from backend.llm.providers.mock_llm.mock_llm import MockLLM, get_mock_llm

__all__ = ["MockLLM", "get_mock_llm"]
