"""Prompt template for the *query_optimizer* node.

Uses :class:`~langchain_core.prompts.ChatPromptTemplate` paired with the LLM
in JSON mode (``response_format={"type": "json_object"}``) so the model streams
regular content tokens that can be forwarded to the frontend in real time.

Catalog data (region names, index labels, GICS sectors) is loaded from the DB
at chain-build time via :func:`build_prompt_template` so the LLM output always
aligns with the live DB constraints used downstream in news classification and
region-index resolution.
"""

from __future__ import annotations

from langchain_core.prompts import ChatPromptTemplate

from backend.db.postgres.queries.fin_markets_region import PromptCatalogs

_JSON_SCHEMA = """\
Your response MUST be a single valid JSON object with exactly these keys:
{{
  "ticker": "<primary ticker symbol, e.g. AAPL>",
  "security_name": "<full company or security name>",
  "industry": "<sub-sector description, e.g. Consumer Electronics, Semiconductors, Cloud Computing>",
  "opposite_industry": "<GICS sector most contrasting to the ticker, from the valid sectors list>",
  "major_peers": ["<ticker1>", "<ticker2>", "<ticker3>"],
  "peer_tickers": ["<ticker1>", "<ticker2>"],
  "region": "<MUST be an exact name from the valid regions list>",
  "ticker_indexes": ["<MUST be exact labels from the valid indexes list — all indexes the ticker belongs to>"]
}}
Produce ONLY the JSON object — no markdown fences, no commentary.
"""


def _build_system_prompt(catalogs: PromptCatalogs) -> str:
    """Compose the system prompt, embedding DB-loaded catalog constraints.

    Args:
        catalogs: Catalog strings loaded from the DB via
                  :func:`~backend.db.queries.fin_markets.get_prompt_catalogs`.

    Returns:
        The full system prompt string.
    """
    region_section = (
        f"--- VALID REGIONS (region field MUST match exactly) ---\n{catalogs.regions}\n\n"
        if catalogs.regions
        else ""
    )
    index_section = (
        f"--- VALID INDEX NAMES (ticker_indexes items MUST match exactly) ---\n"
        f"{catalogs.indexes}\n\n"
        if catalogs.indexes
        else ""
    )
    sector_section = (
        f"--- VALID GICS SECTORS (use for opposite_industry) ---\n{catalogs.sectors}\n\n"
        if catalogs.sectors
        else ""
    )

    return (
        "You are a senior financial research analyst. "
        "Extract structured context from the user's trading or investment query.\n\n"
        "Resolve the following for the primary ticker:\n"
        "  • Full security name and sub-sector description (e.g. 'Consumer Electronics', not just 'Technology')\n"
        "  • The GICS sector most contrasting to the ticker's sector as opposite_industry\n"
        "  • 3–5 major peer ticker symbols; pick exactly 2 for deep comparative analysis\n"
        "  • The geographic region — MUST match exactly one name from the valid regions list\n"
        "  • The specific major index the ticker itself belongs to "
        "— MUST match exactly one label from the valid indexes list\n\n"
        + region_section
        + index_section
        + sector_section
        + _JSON_SCHEMA
    )


def build_prompt_template(catalogs: PromptCatalogs) -> ChatPromptTemplate:
    """Return the ChatPromptTemplate for the query_optimizer chain.

    The template expects a single input variable ``query`` (the raw user query).
    Catalog constraints (regions, indexes, sectors) are embedded in the system
    prompt from ``catalogs``, which must be loaded from the DB beforehand via
    :func:`~backend.db.queries.fin_markets.get_prompt_catalogs`.

    Args:
        catalogs: DB-loaded catalog strings to embed as valid-value constraints.

    Returns:
        A two-message :class:`~langchain_core.prompts.ChatPromptTemplate`.
    """
    return ChatPromptTemplate.from_messages(
        [
            ("system", _build_system_prompt(catalogs)),
            ("human", "{query}"),
        ]
    )
