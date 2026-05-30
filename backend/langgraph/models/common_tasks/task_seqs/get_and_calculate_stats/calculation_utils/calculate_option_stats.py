"""calculate_option_stats — persist an options chain in two steps.

Step 1 — per-contract rows
    Every call/put contract in the payload is parsed from its OSI ``contract_name``
    (:func:`parse_contract_name`) and upserted as an individual row into
    ``fin_markets.quant_options_stats`` keyed on ``(symbol, source, contract_name)``.

Step 2 — per-expiry aggregate
    Contracts are grouped by ``expiry_date``.  For each expiry the underlying price is
    estimated from where the call and put breakevens meet:

        - a call's breakeven is ``strike + call_cost``
        - a put's breakeven  is ``strike - put_cost``

    The two breakevens are closest at the at-the-money (ATM) strike — the strike where
    the combined call+put cost (the straddle) is smallest.  At that ``cross_strike`` the
    estimated underlying is the midpoint of the two breakevens::

        estimated_price = cross_strike + (call_cost - put_cost) / 2

    One aggregate row per expiry is upserted into ``fin_markets.quant_derivative_stats``
    (``derivative_type = 'options'``, ``contract_name = NULL``).

A contract's ``cost`` is its bid/ask midpoint when both quotes are positive, otherwise
its last traded price; contracts with neither are excluded from the aggregate.

Public exports
--------------
``calculate_option_stats``        — ``NodeTask`` instance.
``CalculateOptionStatsInput``     — Pydantic input model.
``CalculateOptionStatsOutput``    — Pydantic output model.
``OptionContractInput``           — Pydantic per-contract input model.
``parse_contract_name``           — OSI contract_name parser.
``HANDLERS``                      — dict slice for Celery handler registration.
"""

from __future__ import annotations

import logging
import re
from datetime import datetime, timezone

from langgraph.func import task
from pydantic import BaseModel, ConfigDict, Field

from backend.celery_task.workers.task_delegation import delegate_completion
from backend.db.postgres import raw_conn
from backend.db.postgres.queries.fin_markets_quant import (
    DerivativeStatsSQL,
    OptionsStatsSQL,
)
from backend.langgraph.lifecycle import complete_task, create_task
from backend.langgraph.models.common_tasks.errors.codes import (
    DERIV_TASK_CALC_ERROR,
    DERIV_TASK_CONTRACT_PARSE_WARN,
    DERIV_TASK_NO_CROSS,
)
from backend.langgraph.models.models import TaskInput, TaskOutput
from backend.langgraph.models.task import NodeTask
from backend.quant.stats import safe_float

logger = logging.getLogger(__name__)

_TASK_NAME = "calculate_option_stats"

# OSI option symbol: root + YYMMDD + C/P + 8-digit strike (thousandths of a dollar).
_OSI_RE = re.compile(r"^([A-Z]+)(\d{6})([CP])(\d{8})$")


# ---------------------------------------------------------------------------
# OSI contract_name parsing
# ---------------------------------------------------------------------------


def parse_contract_name(contract_name: str) -> tuple[str, datetime, str, float]:
    """Parse an OSI option symbol into its components.

    The OSI symbol ``AAPL260601P00250000`` decomposes as
    ``root='AAPL'``, ``YYMMDD='260601'`` (2026-06-01), ``'P'`` (put), and an
    8-digit strike ``00250000`` in thousandths of a dollar (strike ``250.0``).

    Args:
        contract_name: Full OSI contract symbol.

    Returns:
        Tuple ``(root, expiry_date, options_type, strike)`` where ``expiry_date`` is a
        timezone-aware UTC ``datetime`` at midnight, ``options_type`` is ``'call'`` or
        ``'put'``, and ``strike`` is a float.

    Raises:
        ValueError: When *contract_name* is not a valid OSI symbol (carries
            ``DERIV_TASK_CONTRACT_PARSE_WARN``).
    """
    match = _OSI_RE.match(contract_name.strip().upper())
    if match is None:
        raise ValueError(
            f"[{DERIV_TASK_CONTRACT_PARSE_WARN}] cannot parse OSI contract_name "
            f"{contract_name!r}."
        )
    root, ymd, cp, strike_raw = match.groups()
    year, month, day = 2000 + int(ymd[0:2]), int(ymd[2:4]), int(ymd[4:6])
    try:
        expiry_date = datetime(year, month, day, tzinfo=timezone.utc)
    except ValueError as exc:
        raise ValueError(
            f"[{DERIV_TASK_CONTRACT_PARSE_WARN}] invalid expiry date in contract_name "
            f"{contract_name!r}: {exc}."
        ) from exc
    options_type = "call" if cp == "C" else "put"
    strike = int(strike_raw) / 1000.0
    return root, expiry_date, options_type, strike


# ---------------------------------------------------------------------------
# Value coercion helpers
# ---------------------------------------------------------------------------


def _coerce_pct(val: object) -> float | None:
    """Coerce a percent value (``'107.81%'`` or ``107.81``) to a plain float.

    Args:
        val: Raw value, possibly a string with a trailing ``'%'``.

    Returns:
        Float percent (``107.81``) or ``None`` when not numeric.
    """
    if isinstance(val, str):
        val = val.strip().rstrip("%").strip()
    return safe_float(val)


def _parse_iso_datetime(val: object) -> datetime | None:
    """Best-effort parse of an ISO-8601 timestamp into a UTC datetime.

    Args:
        val: Raw value (ISO date/datetime string) or ``None``.

    Returns:
        Timezone-aware UTC ``datetime`` or ``None`` when unparseable.
    """
    if not isinstance(val, str) or not val.strip():
        return None
    text = val.strip().replace("Z", "+00:00")
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _contract_cost(bid: float | None, ask: float | None, last_price: float | None) -> float | None:
    """Return the representative cost of a contract for breakeven aggregation.

    Prefers the bid/ask midpoint when both quotes are positive, otherwise the last
    traded price.

    Args:
        bid:        Bid price or ``None``.
        ask:        Ask price or ``None``.
        last_price: Last traded price or ``None``.

    Returns:
        Float cost, or ``None`` when no usable quote is available.
    """
    if bid is not None and ask is not None and bid > 0 and ask > 0:
        return (bid + ask) / 2.0
    if last_price is not None and last_price > 0:
        return last_price
    return None


# ---------------------------------------------------------------------------
# Pydantic models
# ---------------------------------------------------------------------------


class OptionContractInput(BaseModel):
    """A single call/put contract extracted from an options-chain page.

    Attributes:
        contract_name:      Full OSI option symbol, e.g. ``'AAPL260601P00250000'``.
        options_type:       ``'call'`` or ``'put'`` (informational; the authoritative
                            value is parsed from ``contract_name``).
        strike:             Strike price (informational; parsed from ``contract_name``).
        bid:                Bid price.
        ask:                Ask price.
        last:               Last traded price (page field name).
        last_price:         Last traded price (alternate field name); preferred over ``last``.
        last_trade_date:    Last trade timestamp (ISO-8601 string).
        price_change:       Absolute session price change.
        pct_change:         Percent session price change (``'1.23%'`` or ``1.23``).
        volume:             Session contract volume.
        open_interest:      Per-contract open interest.
        implied_volatility: Implied volatility (``'107.81%'`` or ``107.81``).
    """

    model_config = ConfigDict(extra="ignore")

    contract_name: str
    options_type: str | None = None
    strike: float | None = None
    bid: float | None = None
    ask: float | None = None
    last: float | None = None
    last_price: float | None = None
    last_trade_date: str | None = None
    price_change: float | None = None
    pct_change: float | str | None = None
    volume: float | None = None
    open_interest: float | None = None
    implied_volatility: float | str | None = None


class CalculateOptionStatsInput(BaseModel):
    """Input for the calculate_option_stats handler.

    Attributes:
        symbol:  Underlying ticker symbol, e.g. ``'AAPL'``.
        source:  Data source label persisted with every row, e.g. ``'web_content'``.
        options: Flat list of all call and put contracts extracted from the options chain.
    """

    symbol: str
    source: str = "web_content"
    options: list[OptionContractInput] = Field(default_factory=list)


class VolSmilePoint(BaseModel):
    """A single (strike, implied_volatility) pair for call and/or put at that strike.

    Attributes:
        strike:  Strike price.
        call_iv: Call implied volatility at this strike (percent, e.g. 107.81), or None.
        put_iv:  Put implied volatility at this strike (percent), or None.
    """

    strike: float
    call_iv: float | None = None
    put_iv: float | None = None


class VolSmileExpiry(BaseModel):
    """Per-expiry volatility smile — strike/IV points for one expiry date.

    Attributes:
        expiry_date: Contract maturity as ISO date string, e.g. ``'2026-06-01'``.
        points:      Strike/IV pairs sorted ascending by strike price.
    """

    expiry_date: str
    points: list[VolSmilePoint]


class CalculateOptionStatsOutput(BaseModel):
    """Output from the calculate_option_stats handler.

    Attributes:
        symbol:              Underlying ticker symbol.
        source:              Data source label.
        contracts_upserted:  Per-contract rows written to ``quant_options_stats``.
        contracts_skipped:   Contracts skipped because ``contract_name`` failed to parse.
        expiries_aggregated: Aggregate rows written to ``quant_derivative_stats``.
        expiries_skipped:    Expiries skipped because calls and puts shared no strike.
        stats_views:         Frontend view type list; always ``["VolatilitySmile"]``.
        vol_smile:           Per-expiry volatility smile data for frontend rendering.
    """

    symbol: str
    source: str
    contracts_upserted: int
    contracts_skipped: int
    expiries_aggregated: int
    expiries_skipped: int
    stats_views: list[str] = Field(default_factory=lambda: ["VolatilitySmile"])
    vol_smile: list[VolSmileExpiry] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Celery-layer handler
# ---------------------------------------------------------------------------


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
    symbol = inp.symbol.upper()
    source = inp.source

    contracts_upserted = 0
    contracts_skipped = 0
    expiries_aggregated = 0
    expiries_skipped = 0

    # expiry_date -> {"call": {strike: cost}, "put": {strike: cost}}
    by_expiry: dict[datetime, dict[str, dict[float, float]]] = {}

    # expiry_date -> strike -> {"call": iv | None, "put": iv | None}
    iv_by_expiry: dict[datetime, dict[float, dict[str, float | None]]] = {}

    try:
        async with raw_conn() as conn:
            # --- Step 1: per-contract upserts ---------------------------------
            for contract in inp.options:
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
        symbol=symbol,
        source=source,
        contracts_upserted=contracts_upserted,
        contracts_skipped=contracts_skipped,
        expiries_aggregated=expiries_aggregated,
        expiries_skipped=expiries_skipped,
        vol_smile=vol_smile,
    ).model_dump(mode="json")


# ---------------------------------------------------------------------------
# Celery layer — entry dispatcher
# ---------------------------------------------------------------------------


async def _handler(payload: dict) -> dict:
    """Dispatch the calculate_option_stats payload to the persistence handler.

    Args:
        payload: Serialised :class:`CalculateOptionStatsInput` dict.

    Returns:
        Serialised :class:`CalculateOptionStatsOutput` dict.
    """
    return await calculate_option_stats_handler(payload)


# ---------------------------------------------------------------------------
# LangGraph layer — @task orchestration
# ---------------------------------------------------------------------------


@task
async def _calculate_option_stats_task(
    task_input: TaskInput[CalculateOptionStatsInput],
) -> TaskOutput[CalculateOptionStatsOutput]:
    """LangGraph @task: delegates calculate_option_stats to the Celery completion worker.

    Args:
        task_input: Typed envelope with :class:`~backend.langgraph.models.models.TaskContext`
                    and :class:`CalculateOptionStatsInput` content.

    Returns:
        :class:`~backend.langgraph.models.models.TaskOutput` wrapping
        :class:`CalculateOptionStatsOutput`.
    """
    ctx = task_input.ctx
    payload = task_input.content.model_dump(mode="json")

    await create_task(
        ctx.thread_id, ctx.node_id, ctx.node_name, ctx.task_id, ctx.task_name, payload,
        view_type="Stats",
        stats_views=["VolatilitySmile"],
    )
    try:
        result = await delegate_completion(
            ctx.thread_id, ctx.task_id, ctx.node_id, ctx.node_name, ctx.task_name, payload,
        )
    except Exception as exc:
        await complete_task(
            ctx.thread_id, ctx.node_id, ctx.node_name, ctx.task_id, ctx.task_name,
            failed=True, error=str(exc),
        )
        raise

    output = CalculateOptionStatsOutput.model_validate(result)
    return TaskOutput(ctx=ctx, content=output)


# ---------------------------------------------------------------------------
# NodeTask registration
# ---------------------------------------------------------------------------

calculate_option_stats = NodeTask(
    name=_TASK_NAME,
    description=(
        "Persist an options chain in two steps: upsert each call/put contract into "
        "fin_markets.quant_options_stats, then aggregate per expiry into "
        "fin_markets.quant_derivative_stats by estimating the underlying price where the "
        "call and put breakevens meet at the ATM strike."
    ),
    input_type=CalculateOptionStatsInput,
    output_type=CalculateOptionStatsOutput,
    task_fn=_calculate_option_stats_task,
    handler=_handler,
)

HANDLERS: dict = {_TASK_NAME: _handler}

__all__ = [
    "calculate_option_stats",
    "CalculateOptionStatsInput",
    "CalculateOptionStatsOutput",
    "OptionContractInput",
    "VolSmilePoint",
    "VolSmileExpiry",
    "parse_contract_name",
    "HANDLERS",
]
