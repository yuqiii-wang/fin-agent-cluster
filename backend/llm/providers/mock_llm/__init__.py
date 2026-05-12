"""Mock LLM provider for semantic testing.

Token sequence
--------------
Every stream emits exactly the following tokens in order::

    "<think>"
    … AAPL-related body tokens …
    "</think>"
    JSON summary

Mode
----
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
