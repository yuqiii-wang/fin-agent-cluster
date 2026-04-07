"""Node: Judgement logger — persists report outlook to fin_strategies.judgement_history."""

import logging
import re
from typing import Any

from app.graph.state import FinAnalysisState
from app.graph.nodes.common import log_node_execution, NodeTimer

logger = logging.getLogger(__name__)

# Valid enum values for the DB columns
_VALID_SENTIMENTS = {
    "VERY_NEGATIVE", "NEGATIVE", "SLIGHTLY_NEGATIVE",
    "NEUTRAL",
    "SLIGHTLY_POSITIVE", "POSITIVE", "VERY_POSITIVE",
}
_VALID_CONFIDENCES = {
    "VERY_LOW", "LOW", "MEDIUM", "HIGH", "VERY_HIGH",
}

# Regex to parse the structured OUTLOOK lines from the report
_OUTLOOK_RE = re.compile(
    r"OUTLOOK_(?P<horizon>1D|1W|1M|3M|6M|1Y):\s*"
    r"sentiment=(?P<sentiment>\S+)\s+"
    r"confidence=(?P<confidence>\S+)",
    re.IGNORECASE,
)

# Mapping from horizon tag to (sentiment_column, confidence_column)
_HORIZON_MAP: dict[str, tuple[str, str]] = {
    "1D": ("next_day_sentiment", "next_day_confidence"),
    "1W": ("one_week_sentiment", "one_week_confidence"),
    "1M": ("one_month_sentiment", "one_month_confidence"),
    "3M": ("one_quarter_sentiment", "one_quarter_confidence"),
    "6M": ("half_year_sentiment", "half_year_confidence"),
    "1Y": ("one_year_sentiment", "one_year_confidence"),
}


def _parse_outlook(report: str) -> dict[str, str | None]:
    """Extract per-horizon sentiment and confidence from the report text.

    Args:
        report: Full report text containing OUTLOOK_XX lines.

    Returns:
        Dict mapping DB column names to enum string values.
    """
    result: dict[str, str | None] = {}
    for match in _OUTLOOK_RE.finditer(report):
        horizon = match.group("horizon").upper()
        sentiment = match.group("sentiment").upper()
        confidence = match.group("confidence").upper()

        if horizon not in _HORIZON_MAP:
            continue
        sent_col, conf_col = _HORIZON_MAP[horizon]

        result[sent_col] = sentiment if sentiment in _VALID_SENTIMENTS else None
        result[conf_col] = confidence if confidence in _VALID_CONFIDENCES else None

    return result


async def judgement_logger(state: FinAnalysisState) -> dict[str, Any]:
    """Parse the report's per-horizon outlook and insert a judgement_history row.

    Extracts the consensus sentiment/confidence from the structured OUTLOOK_XX
    block in the report, then inserts into fin_strategies.judgement_history.

    Args:
        state: Current graph state with completed report.

    Returns:
        Dict with judgement_id and step log entry.
    """
    ticker = state.get("security_ticker", "")
    security_id = state.get("security_id")
    report = state.get("report", "")
    logger.info("[judgement_logger] ticker=%s security_id=%s", ticker, security_id)

    if not security_id:
        logger.warning("[judgement_logger] No security_id — skipping judgement log")
        return {
            "judgement_id": None,
            "steps": [f"[judgement_logger] ticker={ticker} skipped (no security_id)"],
        }

    outlook = _parse_outlook(report)
    if not outlook:
        logger.warning("[judgement_logger] Could not parse outlook from report")

    timer = NodeTimer()
    with timer:
        judgement_id = await _insert_judgement(
            security_id=security_id,
            report=report,
            conservative=state.get("conservative_assessment", ""),
            aggressive=state.get("aggressive_assessment", ""),
            extra_analyses={
                "fundamental_analysis": state.get("fundamental_analysis", ""),
                "technical_analysis": state.get("technical_analysis", ""),
                "news_summary": state.get("news_summary", ""),
                "risk_assessment": state.get("risk_assessment", ""),
            },
            outlook=outlook,
        )

    output = {
        "judgement_id": judgement_id,
        "steps": [f"[judgement_logger] ticker={ticker} judgement_id={judgement_id}"],
    }
    await log_node_execution(
        state["thread_id"], "judgement_logger",
        {"ticker": ticker, "security_id": security_id},
        {"judgement_id": judgement_id, "horizons_parsed": len(outlook) // 2},
        timer.started_at, timer.elapsed_ms,
    )
    return output


async def _insert_judgement(
    security_id: int,
    report: str,
    conservative: str,
    aggressive: str,
    extra_analyses: dict[str, str],
    outlook: dict[str, str | None],
) -> int | None:
    """Insert a row into fin_strategies.judgement_history via raw SQL.

    Args:
        security_id: fin_markets.securities.id.
        report: Full report text (stored in rationale).
        conservative: Conservative agent assessment (stored in extra).
        aggressive: Aggressive agent assessment (stored in extra).
        extra_analyses: Intermediate node analyses (fundamental, technical, news, risk).
        outlook: Parsed per-horizon sentiment/confidence columns.

    Returns:
        The new judgement_history.id, or None on failure.
    """
    import json

    from app.database import _get_session_factory

    extra = json.dumps({
        "conservative_assessment": conservative[:2000],
        "aggressive_assessment": aggressive[:2000],
        "fundamental_analysis": extra_analyses.get("fundamental_analysis", "")[:2000],
        "technical_analysis": extra_analyses.get("technical_analysis", "")[:2000],
        "news_summary": extra_analyses.get("news_summary", "")[:2000],
        "risk_assessment": extra_analyses.get("risk_assessment", "")[:2000],
    })

    # Build column/value lists dynamically from parsed outlook
    base_cols = ["security_id", "rationale", "extra"]
    base_vals = [security_id, report[:4000], extra]
    placeholders = [":security_id", ":rationale", ":extra"]

    param_map: dict[str, Any] = {
        "security_id": security_id,
        "rationale": report[:4000],
        "extra": extra,
    }

    for col, val in outlook.items():
        if val is not None:
            base_cols.append(col)
            param_name = col
            placeholders.append(f":{param_name}")
            param_map[param_name] = val

    cols_str = ", ".join(base_cols)
    vals_str = ", ".join(placeholders)

    sql = f"INSERT INTO fin_strategies.judgement_history ({cols_str}) VALUES ({vals_str}) RETURNING id"

    factory = _get_session_factory()
    try:
        async with factory() as session:
            from sqlalchemy import text
            result = await session.execute(text(sql), param_map)
            row = result.fetchone()
            await session.commit()
            return row[0] if row else None
    except Exception:
        logger.exception("[judgement_logger] Failed to insert judgement_history")
        return None
