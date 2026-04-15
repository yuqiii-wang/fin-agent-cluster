"""Prompt template for news article enrichment (classification) step.

Called by ``transform_news_to_stats`` to classify each article batch into
structured metadata fields: region, sector/industry, impact category, and topics.

The prompt lists all valid values the LLM may choose from so the output is
directly insertable into ``fin_markets.news_stats`` without post-processing.
"""

from __future__ import annotations

from langchain_core.prompts import ChatPromptTemplate

# ---------------------------------------------------------------------------
# Catalog strings embedded in the prompt
# ---------------------------------------------------------------------------

_REGIONS = """\
global, amer, us, ca, br, mx,
emea, gb, de, fr, ch, nl, se, no, dk, it, es, sa, ae, qa, il, za,
apac, jp, cn, hk, tw, kr, sg, in, au, nz, id, my, th, ph, vn"""

_SECTORS = """\
technology, healthcare, financials, consumer_discretionary, consumer_staples,
energy, materials, industrials, utilities, real_estate, communication_services, macro"""

_topic_level1 = """\
Corporate, Macro, Geopolitical, Market Structure, Sector & Industry"""

_topic_level2 = """\
Financial Performance, Corporate Strategy, Operations, Legal & Regulatory,
Leadership & Governance, Monetary Policy, Fiscal Policy, Economic Data,
Commodities & Energy, Conflict & Military, Trade Policy, Political Events,
Diplomacy, Equity Actions, Market Events, Index Changes,
Consumer Trends, Tech & Innovation, Sector Regulation, Supply Chain"""

_IMPACT_CODES = """\
earnings_beat, earnings_miss, earnings_in_line, revenue_beat, revenue_miss,
guidance_raised, guidance_lowered, guidance_withdrawn,
merger_acquisition, acquisition_completed, divestiture, strategic_partnership, buyback_announced,
product_launch, product_recall, operational_disruption,
sec_investigation, lawsuit_filed, lawsuit_settled, fda_approval, fda_rejection, antitrust_action,
ceo_change, cfo_change, board_change, insider_buy, insider_sell,
analyst_upgrade, analyst_downgrade, dividend_increase, dividend_cut,
rate_hike, rate_cut, rate_hold, quantitative_easing, quantitative_tightening,
inflation_data, gdp_data, employment_data, pmi_data, consumer_confidence,
commodity_price_spike, commodity_price_drop, oil_supply_shock,
war_outbreak, ceasefire, sanctions_imposed, sanctions_lifted,
trade_war_escalation, trade_deal_signed, tariff_imposed, tariff_removed,
election_result, government_shutdown, political_crisis,
stock_split, ipo, secondary_offering, index_addition, index_removal, short_squeeze,
sector_regulatory_change, industry_disruption, supply_chain_disruption"""


# ---------------------------------------------------------------------------
# Prompt factory
# ---------------------------------------------------------------------------

def build_news_enrichment_prompt() -> ChatPromptTemplate:
    """Return a ChatPromptTemplate for batch news article enrichment.

    The template accepts one variable:
    - ``articles_json``: JSON array of objects, each with ``title`` and ``summary``.

    The LLM must return a JSON array of enrichment objects — one per article —
    in the same order, each containing:
      - ``ai_summary``: 2-3 sentence summary of the article's financial significance
      - ``sentiment``: one of the 9-point sentiment_level enum values (or null)
      - ``region``: one region code from the catalog (or null)
      - ``sector``: one sector code (or null)
      - ``topic_level1``: one of the level1 domain values (or null)
      - ``topic_level2``: one of the level2 category values (or null)
      - ``impact_category``: one impact code (or null)
      - ``topics``: list of concise free-form tags (max 5)

    Returns:
        A :class:`~langchain_core.prompts.ChatPromptTemplate`.
    """
    return ChatPromptTemplate.from_messages([
        (
            "system",
            f"""You are a financial news analyst and classifier. For each news article, \
write a concise AI summary and classify it using the catalogs below.

Your output is inserted DIRECTLY into a PostgreSQL database (fin_markets.news_stats).
Use ONLY the exact catalog values listed — no abbreviations, synonyms, or invented values.
Fields marked REQUIRED must always be non-null; null is acceptable only for truly unknown optional fields.

--- REQUIRED FIELDS ---
ai_summary (text, REQUIRED): 2-3 sentences on what happened and its likely market/price impact.
  Focus on actionable financial implications, not generic descriptions.

sentiment (sentiment_level enum, REQUIRED): the net directional market impact for the relevant asset.
  Allowed values (choose exactly one):
  strongly_bullish | bullish | mildly_bullish | slightly_bullish | neutral |
  slightly_bearish | mildly_bearish | bearish | strongly_bearish

--- OPTIONAL FIELDS (null if cannot be determined with reasonable confidence) ---

region (fin_markets.regions FK — use the PRIMARY geographic focus):
{_REGIONS}
Note: use broader codes (global/emea/apac/amer) when the article spans multiple countries.

sector (fin_markets.news_sector — GICS-aligned):
{_SECTORS}

topic_level1 (impact domain):
{_topic_level1}

topic_level2 (category within domain):
{_topic_level2}

impact_category (most specific event code — choose EXACTLY ONE or null):
{_IMPACT_CODES}

topics (text[], 2-5 concise lowercase tags, e.g. ["ai", "earnings beat", "fed rate hike"]):
  Provide specific, searchable tags — avoid generic words like "news" or "market".

--- OUTPUT ---
Return ONLY a JSON array — no markdown fences, no explanation, no trailing commas.
One object per article in the same order as the input.
Required keys in every object: ai_summary, sentiment, region, sector,
topic_level1, topic_level2, impact_category, topics.""",
        ),
        (
            "human",
            "Classify the following news articles. Return a JSON array with one object per article "
            "in the same order as the input.\n\n"
            "Articles (JSON):\n{articles_json}\n\n"
            'Expected output: [{{"ai_summary": "...", "sentiment": "bullish", "region": "us", '
            '"sector": "technology", "topic_level1": "Corporate", "topic_level2": "Financial Performance", '
            '"impact_category": "earnings_beat", "topics": ["ai", "earnings beat"]}}, ...]',
        ),
    ])
