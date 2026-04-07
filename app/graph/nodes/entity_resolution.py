"""Node 1: Entity resolution — check DB for security/entity, populate if missing."""

import logging
from typing import Any

from sqlalchemy import text

from app.database import _get_session_factory
from app.graph.state import FinAnalysisState
from app.graph.nodes.common import log_node_execution, NodeTimer
from app.quant_api.service import MarketDataService

logger = logging.getLogger(__name__)


async def entity_resolution(state: FinAnalysisState) -> dict[str, Any]:
    """Resolve security ticker to DB ids; fetch from web/LLM and populate if missing.

    Checks fin_markets.securities for the ticker. If not found, uses LLM to
    generate a profile and inserts into both fin_markets.securities and
    fin_markets.entities.

    Args:
        state: Graph state with security_ticker and security_name from query_understanding.

    Returns:
        Dict with security_id, entity_id, entity_description, entity_populated,
        and step log entry.
    """
    ticker = state.get("security_ticker", "")
    sec_name = state.get("security_name", "")
    logger.info("[entity_resolution] ticker=%s name=%s", ticker, sec_name)

    timer = NodeTimer()
    security_id: int | None = None
    entity_id: int | None = None
    entity_desc = ""
    populated = False

    with timer:
        factory = _get_session_factory()

        # 1. Check if security already exists
        async with factory() as session:
            result = await session.execute(
                text(
                    "SELECT s.id, s.description, e.id AS entity_id, e.description AS entity_desc "
                    "FROM fin_markets.securities s "
                    "LEFT JOIN fin_markets.entities e ON e.name = s.name "
                    "WHERE s.ticker = :ticker LIMIT 1"
                ),
                {"ticker": ticker},
            )
            row = result.mappings().first()

        if row:
            security_id = row["id"]
            entity_id = row["entity_id"]
            entity_desc = row["entity_desc"] or row["description"] or ""
            logger.info("[entity_resolution] Found security_id=%s entity_id=%s", security_id, entity_id)
        else:
            # 2. Not found — fetch real profile from yfinance/FMP and insert
            logger.info("[entity_resolution] Not found in DB, fetching via MarketDataService")
            svc = MarketDataService(thread_id=state.get("thread_id"), node_name="entity_resolution")  # auto: yfinance → FMP fallback
            sec_record = await svc.ingest_profile(ticker)
            await svc.close()

            if sec_record:
                # Re-query to get the DB-assigned ids
                async with factory() as session:
                    result = await session.execute(
                        text(
                            "SELECT s.id, s.description, e.id AS entity_id, e.description AS entity_desc "
                            "FROM fin_markets.securities s "
                            "LEFT JOIN fin_markets.entities e ON e.name = s.name "
                            "WHERE s.ticker = :ticker LIMIT 1"
                        ),
                        {"ticker": ticker},
                    )
                    new_row = result.mappings().first()

                if new_row:
                    security_id = new_row["id"]
                    entity_id = new_row["entity_id"]
                    entity_desc = new_row["entity_desc"] or new_row["description"] or ""
            else:
                entity_desc = f"{sec_name} ({ticker})"

            populated = True
            logger.info(
                "[entity_resolution] Created security_id=%s entity_id=%s",
                security_id, entity_id,
            )

    output = {
        "security_id": security_id,
        "entity_id": entity_id,
        "entity_description": entity_desc,
        "entity_populated": populated,
        "steps": [
            f"[entity_resolution] security_id={security_id} entity_id={entity_id} "
            f"populated={populated}"
        ],
    }

    await log_node_execution(
        state["thread_id"],
        "entity_resolution",
        {"ticker": ticker, "security_name": sec_name},
        {"security_id": security_id, "entity_id": entity_id, "populated": populated},
        timer.started_at,
        timer.elapsed_ms,
    )
    return output
