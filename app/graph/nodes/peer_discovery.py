"""Node 2: Peer discovery — find peers, oligopoly members, opposite industry, benchmark."""

import json
import logging
from typing import Any

from sqlalchemy import text

from app.database import _get_session_factory
from app.graph.state import FinAnalysisState
from app.graph.nodes.common import get_llm, log_node_execution, NodeTimer
from app.prompts.peer_discovery import peer_discovery_prompt

logger = logging.getLogger(__name__)


async def peer_discovery(state: FinAnalysisState) -> dict[str, Any]:
    """Discover peers, oligopoly members, opposite industry, and benchmark.

    First checks fin_markets.security_2_security for existing relationships.
    Falls back to LLM if insufficient data found. Persists discovered
    relationships back to the DB for future queries.

    Args:
        state: Graph state with security_ticker, security_name, industry,
               and security_id from entity_resolution.

    Returns:
        Dict with peers, opposite_industry, major_security, and step log.
    """
    ticker = state.get("security_ticker", "")
    sec_name = state.get("security_name", "")
    industry = state.get("industry", "")
    security_id = state.get("security_id")
    logger.info("[peer_discovery] ticker=%s security_id=%s", ticker, security_id)

    timer = NodeTimer()
    peers: dict[str, list[str]] = {}
    opposite_industry = ""
    major_security = ""

    with timer:
        # 1. Check DB for existing relationships
        db_peers_found = False
        if security_id:
            factory = _get_session_factory()
            async with factory() as session:
                result = await session.execute(
                    text(
                        "SELECT rb.relationship_type, s2.ticker "
                        "FROM fin_markets.security_2_security s2s "
                        "JOIN fin_markets.relationship_basics rb ON rb.id = s2s.id "
                        "JOIN fin_markets.securities s2 ON s2.id = s2s.related_id "
                        "WHERE s2s.primary_id = :sid "
                        "ORDER BY rb.relationship_type"
                    ),
                    {"sid": security_id},
                )
                rows = result.mappings().all()

            if rows:
                db_peers_found = True
                for row in rows:
                    rel_type = row["relationship_type"]
                    if rel_type not in peers:
                        peers[rel_type] = []
                    peers[rel_type].append(row["ticker"])
                logger.info("[peer_discovery] Found %d relationships in DB", len(rows))

        # 2. Fall back to LLM if DB has no/insufficient data
        if not db_peers_found:
            logger.info("[peer_discovery] No DB relationships, using LLM")
            llm = get_llm()
            resp = await llm.ainvoke(
                peer_discovery_prompt.invoke({
                    "security_ticker": ticker,
                    "security_name": sec_name,
                    "industry": industry,
                })
            )

            content = resp.content.strip()
            if content.startswith("```"):
                content = content.split("\n", 1)[1].rsplit("```", 1)[0].strip()

            try:
                parsed = json.loads(content)
            except json.JSONDecodeError:
                logger.warning("[peer_discovery] Failed to parse LLM JSON")
                parsed = {}

            peers = {
                "PEER": parsed.get("peers", []),
                "OLIGOPOLY_MEMBER": parsed.get("oligopoly_members", []),
                "SUPPLIER": parsed.get("suppliers", []),
                "CUSTOMER": parsed.get("customers", []),
            }
            opposite_industry = parsed.get("opposite_industry", "")
            major_security = parsed.get("major_security", "SPY")

            # 3. Persist relationships to DB for future queries
            if security_id:
                await _persist_relationships(security_id, peers)

    if not opposite_industry:
        opposite_industry = _get_opposite_industry(industry)
    if not major_security:
        major_security = "SPY"

    output = {
        "peers": peers,
        "opposite_industry": opposite_industry,
        "major_security": major_security,
        "steps": [
            f"[peer_discovery] peers={sum(len(v) for v in peers.values())} "
            f"opposite={opposite_industry} benchmark={major_security}"
        ],
    }

    await log_node_execution(
        state["thread_id"],
        "peer_discovery",
        {"ticker": ticker, "security_id": security_id},
        {"peer_count": sum(len(v) for v in peers.values())},
        timer.started_at,
        timer.elapsed_ms,
    )
    return output


async def _persist_relationships(
    security_id: int, peers: dict[str, list[str]]
) -> None:
    """Persist discovered peer relationships to fin_markets.security_2_security.

    Args:
        security_id: Primary security ID.
        peers: Dict of relationship_type → list of ticker strings.
    """
    factory = _get_session_factory()
    async with factory() as session:
        for rel_type, tickers in peers.items():
            for ticker in tickers:
                # Resolve related ticker to id
                result = await session.execute(
                    text(
                        "SELECT id FROM fin_markets.securities WHERE ticker = :ticker LIMIT 1"
                    ),
                    {"ticker": ticker},
                )
                row = result.first()
                if not row:
                    continue
                related_id = row[0]

                await session.execute(
                    text(
                        "INSERT INTO fin_markets.security_2_security "
                        "(primary_id, related_id, relationship_type, published_at) "
                        "VALUES (:primary_id, :related_id, :rel_type, NOW()) "
                        "ON CONFLICT DO NOTHING"
                    ),
                    {
                        "primary_id": security_id,
                        "related_id": related_id,
                        "rel_type": rel_type,
                    },
                )
        await session.commit()


def _get_opposite_industry(industry: str) -> str:
    """Return a counter-cyclical industry for hedging.

    Args:
        industry: GICS sector name.

    Returns:
        Opposite industry sector name.
    """
    opposites = {
        "INFORMATION_TECHNOLOGY": "UTILITIES",
        "CONSUMER_DISCRETIONARY": "CONSUMER_STAPLES",
        "ENERGY": "INFORMATION_TECHNOLOGY",
        "FINANCIALS": "UTILITIES",
        "HEALTH_CARE": "ENERGY",
        "INDUSTRIALS": "UTILITIES",
        "MATERIALS": "INFORMATION_TECHNOLOGY",
        "COMMUNICATION_SERVICES": "UTILITIES",
        "UTILITIES": "INFORMATION_TECHNOLOGY",
        "REAL_ESTATE": "INFORMATION_TECHNOLOGY",
        "CONSUMER_STAPLES": "CONSUMER_DISCRETIONARY",
    }
    return opposites.get(industry, "UTILITIES")
