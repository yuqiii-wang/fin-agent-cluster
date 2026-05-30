"""navigate_web.py — Step 1: propose URLs then crawl, study and extract options JSON in parallel."""

from __future__ import annotations

import json
import logging
from typing import Any

from backend.langgraph.models.common_tasks.task_seqs.navigate_web.models import (
    NavigateWebInput,
    NavigateWebPerUrlOutput,
)
from backend.langgraph.models.common_tasks.task_seqs.navigate_web.seq import navigate_web
from backend.langgraph.nodes.prepare_derivatives.agent_steps.constants import STEP_NAVIGATE_WEB
from backend.langgraph.nodes.prepare_derivatives.models.state import DerivativesStepContext

logger = logging.getLogger(__name__)

_NAVIGATE_OBJECTIVE = (
    "Find options chain, derivatives contracts, and related market data for the equity symbol {symbol}."
)

_CONTRACT_SCHEMA: dict = {
    "type": "object",
    "properties": {
        "contract_name": {
            "type": "string",
            "description": "Full OSI symbol, e.g. 'AAPL260529C00150000'.",
        },
        "options_type": {
            "type": "string",
            "description": "'call' or 'put'.",
        },
        "strike": {
            "type": "number",
            "description": "Strike price.",
        },
        "bid": {"type": "number", "description": "Bid price."},
        "ask": {"type": "number", "description": "Ask price."},
        "last_price": {"type": "number", "description": "Last traded price."},
        "last_trade_date": {
            "type": "string",
            "description": "ISO-8601 UTC datetime of the last trade.",
        },
        "price_change": {"type": "number", "description": "Absolute session price change."},
        "pct_change": {
            "type": "number",
            "description": "Percent session price change (plain number, e.g. 1.23).",
        },
        "volume": {"type": "number", "description": "Session contract volume."},
        "open_interest": {"type": "number", "description": "Per-contract open interest."},
        "implied_volatility": {
            "type": "number",
            "description": "Implied volatility as a plain percent number, e.g. 107.81 (not '107.81%').",
        },
    },
    "required": ["contract_name", "options_type", "strike"],
}

_DERIVATIVES_OUTPUT_SCHEMA: dict = {
    "type": "object",
    "properties": {
        "data_type": {
            "type": "string",
            "description": "Must always be 'options'.",
        },
        "options": {
            "type": "array",
            "description": "Flat list of all call and put contracts extracted from the options chain.",
            "items": _CONTRACT_SCHEMA,
        },
    },
    "required": ["data_type", "options"],
}

_ADDITIONAL_CONTEXT: list[str] = [
    "CRITICAL — the output JSON MUST always set data_type to 'options' "
    "(the only supported value). "
    "Output a single flat 'options' list containing ALL call and put contracts. "
    "Every entry must include contract_name (OSI format, e.g. AAPL260529C00150000), "
    "options_type ('call' or 'put'), and strike. "
    "If the page contains no extractable contracts, output an empty list for 'options' "
    "but still set data_type='options'.",
]


def _merge_options_results(
    per_url_results: list[NavigateWebPerUrlOutput],
    symbol: str,
) -> dict[str, Any] | None:
    """Merge options JSON from all successful URL pipeline runs.

    Deduplicates contracts across results by ``contract_name``.  Returns
    ``None`` when no result produced a valid options JSON.

    Args:
        per_url_results: Successful per-URL pipeline outputs.
        symbol:          Equity symbol for logging context.

    Returns:
        Merged options dict with ``data_type='options'`` and a flat ``options`` list;
        or ``None`` if no valid options JSON was found.
    """
    seen: dict[str, dict] = {}  # contract_name -> contract dict

    for result in per_url_results:
        sandbox = result.run_sandbox
        if sandbox.exit_code != 0 or not sandbox.stdout:
            continue
        try:
            parsed = json.loads(sandbox.stdout)
        except (json.JSONDecodeError, ValueError) as exc:
            logger.error("[PD-003f] sandbox stdout JSON parse error symbol=%r: %s", symbol, exc)
            continue

        if "data_type" not in parsed:
            parsed["data_type"] = "options"

        if parsed.get("data_type") != "options":
            logger.error(
                "[PD-003g] unexpected data_type=%r in sandbox output symbol=%r — skipping",
                parsed.get("data_type"),
                symbol,
            )
            continue

        for contract in parsed.get("options") or []:
            key = contract.get("contract_name")
            if key and key not in seen:
                seen[key] = contract

    if not seen:
        return None

    return {
        "data_type": "options",
        "options": list(seen.values()),
    }


async def step_navigate_web(sctx: DerivativesStepContext) -> None:
    """Step 1: propose URLs then crawl, study and extract options JSON in parallel.

    Runs the full ``navigate_web`` TaskSeq (propose → parallel crawl/study/sandbox)
    for the target equity symbol.  Merges calls and puts from all successful URL
    results (deduplicated by ``contract_name``) and stores the result in
    ``sctx.g.json_input`` for downstream steps.

    Fail-open: errors are logged but do not raise so later steps can still
    attempt OHLCV-only stats.

    Args:
        sctx: Step context.
    """
    g = sctx.g

    if not g.symbol:
        logger.error("[PD-001] No stock symbol available — skipping navigate_web step.")
        return

    try:
        nav_output = await navigate_web.run(
            sctx.run_task,
            sctx.ctx,
            NavigateWebInput(
                symbol=g.symbol,
                objective=_NAVIGATE_OBJECTIVE.format(symbol=g.symbol),
                output_json_schema=_DERIVATIVES_OUTPUT_SCHEMA,
                additional_context=_ADDITIONAL_CONTEXT,
                max_links=50,
            ),
        )
    except Exception as exc:
        logger.error("[PD-002] navigate_web failed symbol=%r: %s", g.symbol, exc)
        return

    # Populate fallback markdown output from the first successful URL pipeline
    # so step_get_stats can store page content even when sandbox extraction fails.
    if nav_output.results:
        g.load_md_output = nav_output.results[0]

    if not nav_output.results:
        logger.error(
            "[PD-003] navigate_web returned no successful URL results symbol=%r "
            "url=%r",
            g.symbol,
            nav_output.propose_web_knowledge_urls.url,
        )
        return

    merged = _merge_options_results(nav_output.results, g.symbol)
    if merged is None:
        logger.error(
            "[PD-003h] no valid options JSON extracted from any URL symbol=%r", g.symbol
        )
        return

    g.json_input = merged


__all__ = ["step_navigate_web"]
