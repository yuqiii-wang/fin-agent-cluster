"""
Unified LLM interface for the backend.
The Interface is a dict that by what key to get the LLM provider.
"""

from backend.llm.factory import LLMProvider, get_llm

__all__ = ["get_llm", "LLMProvider"]
