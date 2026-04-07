"""LangGraph financial analysis workflow builder.

10-node hybrid topology with AsyncPostgresSaver (pg saver) checkpointing:

  START → query_understanding → entity_resolution → peer_discovery
        → market_data_collector ──┐
        → fundamental_analyzer ───┤  (parallel fan-out from peer_discovery)
        → news_collector ─────────┘
        → technical_analyzer (from market_data_collector)
        → conservative_risk_agent ─┐  (parallel fan-in from fundamental + technical + news)
        → aggressive_profit_agent ─┘
        → report_generator (fan-in from both agents)
        → judgement_logger → END
"""

from langgraph.graph import StateGraph, START, END

from app.graph.state import FinAnalysisState
from app.graph.nodes.query_understanding import query_understanding
from app.graph.nodes.entity_resolution import entity_resolution
from app.graph.nodes.peer_discovery import peer_discovery
from app.graph.nodes.market_data import market_data_collector
from app.graph.nodes.fundamental import fundamental_analyzer
from app.graph.nodes.technical import technical_analyzer
from app.graph.nodes.news_collector import news_collector
from app.graph.nodes.conservative_agent import conservative_risk_agent
from app.graph.nodes.aggressive_agent import aggressive_profit_agent
from app.graph.nodes.report import report_generator
from app.graph.nodes.judgement_logger import judgement_logger


def build_graph() -> StateGraph:
    """Construct the 10-node financial analysis graph (uncompiled).

    Topology:
      sequential (understand → resolve → discover peers)
        → parallel fan-out (market_data, fundamental, news)
        → sequential (technical from market_data)
        → parallel fan-out (conservative_risk_agent, aggressive_profit_agent)
           both wait for fundamental + technical + news (fan-in)
        → fan-in (report_generator waits for both agents)
        → sequential (judgement_logger persists to fin_strategies.judgement_history)

    The caller must compile with an AsyncPostgresSaver checkpointer:
        async with checkpointer() as cp:
            compiled = build_graph().compile(checkpointer=cp)

    Returns:
        Uncompiled StateGraph ready for .compile(checkpointer=...).
    """
    builder = StateGraph(FinAnalysisState)

    # Add all nodes
    builder.add_node("query_understanding", query_understanding)
    builder.add_node("entity_resolution", entity_resolution)
    builder.add_node("peer_discovery", peer_discovery)
    builder.add_node("market_data_collector", market_data_collector)
    builder.add_node("fundamental_analyzer", fundamental_analyzer)
    builder.add_node("technical_analyzer", technical_analyzer)
    builder.add_node("news_collector", news_collector)
    builder.add_node("conservative_risk_agent", conservative_risk_agent)
    builder.add_node("aggressive_profit_agent", aggressive_profit_agent)
    builder.add_node("report_generator", report_generator)
    builder.add_node("judgement_logger", judgement_logger)

    # Step 1 – sequential: understand query → resolve entity → discover peers
    builder.add_edge(START, "query_understanding")
    builder.add_edge("query_understanding", "entity_resolution")
    builder.add_edge("entity_resolution", "peer_discovery")

    # Step 2 – parallel fan-out from peer_discovery:
    #   market_data_collector, fundamental_analyzer, news_collector
    builder.add_edge("peer_discovery", "market_data_collector")
    builder.add_edge("peer_discovery", "fundamental_analyzer")
    builder.add_edge("peer_discovery", "news_collector")

    # Step 3 – technical_analyzer depends on market_data
    builder.add_edge("market_data_collector", "technical_analyzer")

    # Step 4 – parallel fan-out: both perspective agents wait for
    #   fundamental + technical + news (fan-in triggers)
    builder.add_edge("fundamental_analyzer", "conservative_risk_agent")
    builder.add_edge("technical_analyzer", "conservative_risk_agent")
    builder.add_edge("news_collector", "conservative_risk_agent")

    builder.add_edge("fundamental_analyzer", "aggressive_profit_agent")
    builder.add_edge("technical_analyzer", "aggressive_profit_agent")
    builder.add_edge("news_collector", "aggressive_profit_agent")

    # Step 5 – fan-in: report_generator waits for both agent perspectives
    builder.add_edge("conservative_risk_agent", "report_generator")
    builder.add_edge("aggressive_profit_agent", "report_generator")

    # Step 6 – log judgement to fin_strategies.judgement_history
    builder.add_edge("report_generator", "judgement_logger")
    builder.add_edge("judgement_logger", END)

    return builder
