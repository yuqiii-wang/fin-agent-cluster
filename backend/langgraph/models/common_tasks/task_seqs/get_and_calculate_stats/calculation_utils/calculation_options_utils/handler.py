"""handler -- Celery-layer persistence handler for options stats.

Provides:
- ``calculate_option_stats_handler``: persist an options chain (per-contract rows)
  to the database and compute per-expiry metrics (vol smile, PC ratios) in memory.
- ``_handler``: thin dispatch wrapper for Celery task registration.
"""

from __future__ import annotations

import logging
from datetime import datetime

from backend.db.postgres import raw_conn
from backend.db.postgres.queries.fin_markets_quant import (
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
    PcRatioPoint,
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


def _positive_float(value: object) -> float | None:
    """Return ``value`` as a non-negative finite float or ``None`` when missing.

    Accepts numeric types and strings.  NaN/negative/empty values all collapse
    to ``None`` so downstream aggregations skip them cleanly instead of
    producing negative or NaN sums.
    """
    if value is None:
        return None
    if isinstance(value, bool):
        return None
    try:
        f = float(value)
    except (TypeError, ValueError):
        return None
    if f != f:  # NaN
        return None
    if f < 0:
        return None
    return f


async def calculate_option_stats_handler(payload: dict) -> dict:
    """Persist an options chain as per-contract rows and compute per-expiry metrics.

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

    # Per-expiry rolling totals used to compute Put/Call ratios even when some
    # contracts are missing volume / open_interest fields.
    # expiry_date -> {"call": {"volume": float, "oi": float}, "put": {...}}
    pc_totals: dict[datetime, dict[str, dict[str, float]]] = {}

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

                # Volume / open interest: accept when positive; otherwise propagate
                # NULL so providers that only return one of the two still produce
                # a sensible aggregate.
                volume = _positive_float(contract.volume)
                open_interest = _positive_float(contract.open_interest)

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
                        "volume":             volume,
                        "open_interest":      open_interest,
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
                if volume is not None and volume > 0:
                    vol_strikes = volume_by_expiry.setdefault(expiry_date, {})
                    vol_strikes.setdefault(strike, {})[options_type] = volume

                # Accumulate per-side totals for Put/Call ratio.  Missing fields
                # contribute zero; when every contract on one side is missing the
                # aggregate remains zero, which the SQL layer converts to NULL.
                side = pc_totals.setdefault(
                    expiry_date, {"call": {"volume": 0.0, "oi": 0.0}, "put": {"volume": 0.0, "oi": 0.0}}
                )[options_type]
                if volume is not None:
                    side["volume"] += volume
                if open_interest is not None:
                    side["oi"] += open_interest

            # --- Step 2: per-expiry aggregate tracking -----------------------
            # Track expiries that have any tracked cost data, counting shared
            # strikes for informational purposes.
            all_expiries: set[datetime] = set(by_expiry) | set(pc_totals)

            for expiry_date in sorted(all_expiries):
                legs = by_expiry.get(expiry_date, {"call": {}, "put": {}})
                call_costs = legs["call"]
                put_costs = legs["put"]
                common_strikes = call_costs.keys() & put_costs.keys()

                if common_strikes:
                    expiries_aggregated += 1
                else:
                    expiries_skipped += 1
                    logger.warning(
                        "[%s] no shared strike between calls/puts symbol=%r expiry=%s",
                        DERIV_TASK_NO_CROSS, symbol, expiry_date.date().isoformat(),
                    )
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

    # --- Put/Call ratio per expiry plus overall -------------------------------
    # NOTE: only the two schema columns are reported; the "total" blend
    # is dropped because the schema keeps per-metric ratios only.
    pc_ratio_points: list[PcRatioPoint] = []
    total_call_volume = 0.0
    total_put_volume = 0.0
    total_call_oi = 0.0
    total_put_oi = 0.0
    for expiry_dt, sides in pc_totals.items():
        call_v = sides["call"]["volume"] or None
        put_v = sides["put"]["volume"] or None
        call_oi = sides["call"]["oi"] or None
        put_oi = sides["put"]["oi"] or None

        ratio_volume = round(put_v / call_v, 4) if (call_v and put_v) else None
        ratio_oi = round(put_oi / call_oi, 4) if (call_oi and put_oi) else None
        if call_v and put_v:
            total_call_volume += call_v
            total_put_volume += put_v
        if call_oi and put_oi:
            total_call_oi += call_oi
            total_put_oi += put_oi

        pc_ratio_points.append(
            PcRatioPoint(
                expiry_date=expiry_dt.date().isoformat(),
                call_volume=call_v,
                put_volume=put_v,
                call_open_interest=call_oi,
                put_open_interest=put_oi,
                put_call_volume_ratio=ratio_volume,
                put_call_open_interest_ratio=ratio_oi,
            )
        )
    overall_ratio: float | None = None
    if total_call_volume > 0 and total_put_volume > 0:
        overall_ratio = round(total_put_volume / total_call_volume, 4)
    elif total_call_oi > 0 and total_put_oi > 0:
        overall_ratio = round(total_put_oi / total_call_oi, 4)

    return CalculateOptionStatsOutput(
        rows_upserted=contracts_upserted,
        symbol=symbol,
        source=source,
        contracts_upserted=contracts_upserted,
        contracts_skipped=contracts_skipped,
        expiries_aggregated=expiries_aggregated,
        expiries_skipped=expiries_skipped,
        vol_smile=vol_smile,
        put_call_ratios=pc_ratio_points,
        put_call_ratio_overall=overall_ratio,
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
