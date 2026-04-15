"""LangChain chain for the market_data_collector synthesis step.

Combines the ChatPromptTemplate with the LLM and a StrOutputParser so the
chain accepts {"query": str, "real_data_context": str} and returns a string.
"""

from __future__ import annotations

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.output_parsers import StrOutputParser
from langchain_core.runnables import Runnable

from backend.graph.prompts.market_data import build_prompt_template


def build_chain(llm: BaseChatModel) -> Runnable:
    """Return a chain that maps {"query": str, "real_data_context": str} → str.

    The chain is: ``ChatPromptTemplate | llm | StrOutputParser``.

    Args:
        llm: A LangChain chat model instance.

    Returns:
        A Runnable accepting ``{"query", "real_data_context"}`` and returning str.
    """
    prompt = build_prompt_template()
    return prompt | llm | StrOutputParser()
