"""Agent state schemas for LangGraph workflows."""

from typing import Annotated, Any, TypedDict


def _merge_lists(a: list[str], b: list[str]) -> list[str]:
    """Merge two step-log lists (LangGraph reducer)."""
    return a + b


def _merge_dicts(a: dict[str, Any], b: dict[str, Any]) -> dict[str, Any]:
    """Shallow-merge two dicts (LangGraph reducer for peers/relationships)."""
    merged = {**a}
    merged.update(b)
    return merged


class FinAnalysisState(TypedDict):
    """Shared state flowing through the financial analysis LangGraph workflow.

    Node pipeline:
      query_understanding → entity_resolution → peer_discovery
        → market_data_collector + fundamental_analyzer + news_collector (parallel)
        → conservative_risk_agent + aggressive_profit_agent (parallel fan-in)
        → report_generator (fan-in)
        → judgement_logger → END

    Fields:
      query               – raw user query text
      thread_id           – LangGraph thread correlation ID

      # query_understanding outputs
      security_ticker     – resolved primary ticker (e.g. "AAPL")
      security_name       – human-readable security name
      industry            – GICS sector (e.g. "INFORMATION_TECHNOLOGY")
      query_intent        – parsed intent summary from LLM
      extra_context       – any extra structured context from LLM parsing

      # entity_resolution outputs
      security_id         – fin_markets.securities.id (None if not found)
      entity_id           – fin_markets.entities.id (None if not found)
      entity_description  – entity description from web / DB
      entity_populated    – whether entity data was created/refreshed

      # peer_discovery outputs
      peers               – dict of relationship_type → list of ticker strings
      opposite_industry   – counter-cyclical / hedge industry
      major_security      – benchmark / index ticker

      # analysis outputs
      market_data         – market data collector output
      fundamental_analysis – fundamental analyzer output
      technical_analysis  – technical analyzer output (from market_data node)
      news_summary        – news collector output

      # dual-perspective assessment
      conservative_assessment – conservative risk agent commentary
      aggressive_assessment   – aggressive profit seeker commentary

      # final report
      report              – final report with key metrics + both perspectives

      # judgement history
      judgement_id        – fin_strategies.judgement_history.id (None before logging)

      steps               – accumulating log of node executions
    """

    query: str
    thread_id: str

    # query_understanding
    security_ticker: str
    security_name: str
    industry: str
    query_intent: str
    extra_context: Annotated[dict[str, Any], _merge_dicts]

    # entity_resolution
    security_id: int | None
    entity_id: int | None
    entity_description: str
    entity_populated: bool

    # peer_discovery
    peers: Annotated[dict[str, Any], _merge_dicts]
    opposite_industry: str
    major_security: str

    # analysis
    market_data: str
    fundamental_analysis: str
    technical_analysis: str
    news_summary: str

    # dual-perspective assessment
    conservative_assessment: str
    aggressive_assessment: str

    # final report
    report: str

    # judgement history persistence
    judgement_id: int | None

    steps: Annotated[list[str], _merge_lists]
