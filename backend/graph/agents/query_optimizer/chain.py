"""LangChain chain for the query_optimizer node.

Combines the ChatPromptTemplate with the LLM in JSON mode so the model
streams regular content tokens that can be forwarded via SSE.  The caller
is responsible for parsing the accumulated JSON text into a
:class:`~backend.graph.agents.query_optimizer.models.LLMRawContext` object.
"""

from __future__ import annotations

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.output_parsers import StrOutputParser
from langchain_core.runnables import Runnable

from backend.db.postgres.queries.fin_markets_region import get_prompt_catalogs
from backend.graph.prompts.query_optimizer import build_prompt_template


async def build_chain(llm: BaseChatModel) -> Runnable:
    """Return a chain that maps ``{"query": str}`` → JSON string.

    Fetches catalog data (regions, index labels, GICS sectors) from the DB
    and embeds them as hard constraints in the system prompt, then wires the
    prompt to the LLM with ``response_format={"type": "json_object"}`` so the
    model emits content tokens enabling live token streaming to the sidebar.
    The chain does **not** validate the output — callers must parse via
    :class:`~backend.graph.agents.query_optimizer.models.LLMRawContext`.

    Args:
        llm: A LangChain chat model instance (must support JSON mode binding).

    Returns:
        A :class:`~langchain_core.runnables.Runnable` that accepts
        ``{"query": str}`` and returns a raw JSON string from the LLM.
    """
    catalogs = await get_prompt_catalogs()
    prompt = build_prompt_template(catalogs)
    json_llm = llm.bind(response_format={"type": "json_object"})
    return prompt | json_llm | StrOutputParser()
