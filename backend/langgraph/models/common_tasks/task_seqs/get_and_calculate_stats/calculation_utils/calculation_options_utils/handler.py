"""handler — Celery-layer persistence handler for options stats.

Provides:
- ``calculate_option_stats_handler``: persist an options chain (per-contract rows +
  per-expiry aggregates) to the database.
- ``_handler``: thin dispatch wrapper for Celery task registration.
"""

from __future__ import annotations

import logging
from datetime import datetime

from backend.db.postgres import raw_conn
from backend.db.postgres.queries.fin_markets_quant import (
    DerivativeStatsSQL,
    OptionsStatsSQL,
)
from backend.langgraph.models.common_tasks.errors.codes import (
    DERIV_TASK_CALC_ERROR,
    DERIV_TASK_NO_CROSS,
)
from backend.quant.stats import safe_float

from .models import (
    CalculateOptionStatsInput,
    CalculateOptionStatsOutput,
    VolSmileExpiry,
    VolSmilePoint,
)
from .parsers import (
    _coerce_pct,
    _contract_cost,
    _parse_iso_datetime,
    parse_contract_name,
)
from .parser_utils import (
    extract_value,
    parse_numeric_value,
    parse_integer_value,
    parse_percent_value,
    parse_contract_name_from_link,
)

logger = logging.getLogger(__name__)


async def calculate_option_stats_handler(payload: dict) -> dict:
    """Persist an options chain as per-contract rows plus per-expiry aggregates.

    Args:
        payload: Serialised :class:`CalculateOptionStatsInput` dict.

    Returns:
        Serialised :class:`CalculateOptionStatsOutput` dict.

    Raises:
        RuntimeError: When a DB write fails (carries ``DERIV_TASK_CALC_ERROR``).
    """
    inp = CalculateOptionStatsInput.model_validate(payload)
    symbol = inp.resolved_symbol.upper()
    source = inp.source

    contracts_upserted = 0
    contracts_skipped = 0
    expiries_aggregated = 0
    expiries_skipped = 0

    # expiry_date -> {"call": {strike: cost}, "put": {strike: cost}}
    by_expiry: dict[datetime, dict[str, dict[float, float]]] = {}

    # expiry_date -> strike -> {"call": iv | None, "put": iv | None}
    iv_by_expiry: dict[datetime, dict[float, dict[str, float | None]]] = {}

    # expiry_date -> strike -> {"call": cost | None, "put": cost | None}
    cost_by_expiry: dict[datetime, dict[float, dict[str, float | None]]] = {}

    # expiry_date -> strike -> {"call": volume | None, "put": volume | None}
    volume_by_expiry: dict[datetime, dict[float, dict[str, float | None]]] = {}

    try:
        async with raw_conn() as conn:
            # --- Step 1: per-contract upserts ---------------------------------
            for contract in inp.resolved_options:
                try:
                    root, expiry_date, options_type, strike = parse_contract_name(
                        contract.contract_name
                    )
                except ValueError as exc:
                    contracts_skipped += 1
                    logger.warning("%s symbol=%r", exc, symbol)
                    continue

                bid = safe_float(contract.bid)
                ask = safe_float(contract.ask)
                last_price = safe_float(
                    contract.last_price if contract.last_price is not None else contract.last
                )
                implied_volatility = _coerce_pct(contract.implied_volatility)
                pct_change = _coerce_pct(contract.pct_change)

                await conn.execute(
                    OptionsStatsSQL.UPSERT,
                    {
                        "symbol":             symbol,
                        "source":             source,
                        "contract_name":      contract.contract_name.strip().upper(),
                        "options_type":       options_type,
                        "expiry_date":        expiry_date,
                        "strike":             strike,
                        "last_trade_date":    _parse_iso_datetime(contract.last_trade_date),
                        "last_price":         last_price,
                        "bid":                bid,
                        "ask":                ask,
                        "price_change":       safe_float(contract.price_change),
                        "pct_change":         pct_change,
                        "volume":             safe_float(contract.volume),
                        "open_interest":      safe_float(contract.open_interest),
                        "implied_volatility": implied_volatility,
                    },
                )
                contracts_upserted += 1

                cost = _contract_cost(bid, ask, last_price)
                if cost is not None:
                    legs = by_expiry.setdefault(expiry_date, {"call": {}, "put": {}})
                    legs[options_type][strike] = cost

                if implied_volatility is not None and implied_volatility > 0:
                    iv_strikes = iv_by_expiry.setdefault(expiry_date, {})
                    iv_strikes.setdefault(strike, {})[options_type] = implied_volatility

                # Track costs for volatility smile (even if IV is missing)
                if cost is not None:
                    cost_strikes = cost_by_expiry.setdefault(expiry_date, {})
                    cost_strikes.setdefault(strike, {})[options_type] = cost

                # Track volume for volatility smile bar chart
                volume = safe_float(contract.volume)
                if volume is not None and volume > 0:
                    vol_strikes = volume_by_expiry.setdefault(expiry_date, {})
                    vol_strikes.setdefault(strike, {})[options_type] = volume

            # --- Step 2: per-expiry aggregate upserts -------------------------
            for expiry_date, legs in by_expiry.items():
                call_costs = legs["call"]
                put_costs = legs["put"]
                common_strikes = call_costs.keys() & put_costs.keys()
                if not common_strikes:
                    expiries_skipped += 1
                    logger.warning(
                        "[%s] no shared strike between calls/puts symbol=%r expiry=%s",
                        DERIV_TASK_NO_CROSS, symbol, expiry_date.date().isoformat(),
                    )
                    continue

                # ATM strike: smallest straddle cost = where call/put breakevens meet.
                cross_strike = min(
                    common_strikes, key=lambda k: call_costs[k] + put_costs[k]
                )
                estimated_price = cross_strike + (
                    call_costs[cross_strike] - put_costs[cross_strike]
                ) / 2.0

                await conn.execute(
                    DerivativeStatsSQL.UPSERT_OPTIONS_AGGREGATE,
                    {
                        "symbol":          symbol,
                        "source":          source,
                        "expiry_date":     expiry_date,
                        "estimated_price": estimated_price,
                        "cross_strike":    cross_strike,
                    },
                )
                expiries_aggregated += 1
    except Exception as exc:
        logger.error(
            "[%s] options stats persistence failed symbol=%r: %s",
            DERIV_TASK_CALC_ERROR, symbol, exc,
        )
        raise RuntimeError(f"[{DERIV_TASK_CALC_ERROR}] {exc}") from exc

    vol_smile: list[VolSmileExpiry] = [
        VolSmileExpiry(
            expiry_date=expiry_dt.date().isoformat(),
            points=[
                VolSmilePoint(
                    strike=s,
                    call_iv=iv_by_expiry[expiry_dt][s].get("call"),
                    put_iv=iv_by_expiry[expiry_dt][s].get("put"),
                    call_cost=cost_by_expiry.get(expiry_dt, {}).get(s, {}).get("call"),
                    put_cost=cost_by_expiry.get(expiry_dt, {}).get(s, {}).get("put"),
                    call_volume=volume_by_expiry.get(expiry_dt, {}).get(s, {}).get("call"),
                    put_volume=volume_by_expiry.get(expiry_dt, {}).get(s, {}).get("put"),
                )
                for s in sorted(iv_by_expiry[expiry_dt])
            ],
        )
        for expiry_dt in sorted(iv_by_expiry)
        if any(
            v.get("call") is not None or v.get("put") is not None
            for v in iv_by_expiry[expiry_dt].values()
        )
    ]

    return CalculateOptionStatsOutput(
        rows_upserted=contracts_upserted + expiries_aggregated,
        symbol=symbol,
        source=source,
        contracts_upserted=contracts_upserted,
        contracts_skipped=contracts_skipped,
        expiries_aggregated=expiries_aggregated,
        expiries_skipped=expiries_skipped,
        vol_smile=vol_smile,
    ).model_dump(mode="json")


async def _handler(payload: dict) -> dict:
    """Dispatch the calculate_option_stats payload to the persistence handler.

    Args:
        payload: Serialised :class:`CalculateOptionStatsInput` dict.

    Returns:
        Serialised :class:`CalculateOptionStatsOutput` dict.
    """
    return await calculate_option_stats_handler(payload)


__all__ = [
    "calculate_option_stats_handler",
    "_handler",
]
