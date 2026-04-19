"""FastAPI router for quant technical indicator endpoints.

Endpoints:
    GET /quant/indicators                           — static indicator metadata list
    GET /quant/stats/{symbol}/{granularity}         — time-series for one indicator
    GET /quant/symbol-currency/{symbol}             — currency info for a symbol
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, HTTPException, Query
from psycopg.rows import dict_row
from pydantic import BaseModel

from backend.db import raw_conn
from backend.db.postgres.queries.fin_markets_quant import OhlcvStatsSQL
from backend.db.postgres.queries.fin_markets_region import get_currency_for_symbol

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/quant", tags=["quant"])

# ── Indicator registry ────────────────────────────────────────────────────────
# Each entry describes one selectable indicator option in the UI.
# Keys:
#   id        – unique identifier used as the ``indicator`` query param
#   label     – human-readable dropdown label
#   group     – category for <Select> option-group display
#   overlay   – True → plot on price chart; False → separate panel chart
#   columns   – DB column names to SELECT (len > 1 = multi-line response)
#   keys      – response field names corresponding to each column
_INDICATORS: list[dict[str, Any]] = [
    # Moving Averages (overlay on price chart)
    {"id": "sma_20",   "label": "SMA 20",          "group": "Moving Averages", "overlay": True,  "columns": ["sma_20"],                              "keys": ["value"]},
    {"id": "sma_50",   "label": "SMA 50",          "group": "Moving Averages", "overlay": True,  "columns": ["sma_50"],                              "keys": ["value"]},
    {"id": "sma_200",  "label": "SMA 200",         "group": "Moving Averages", "overlay": True,  "columns": ["sma_200"],                             "keys": ["value"]},
    {"id": "ema_12",   "label": "EMA 12",          "group": "Moving Averages", "overlay": True,  "columns": ["ema_12"],                              "keys": ["value"]},
    {"id": "ema_26",   "label": "EMA 26",          "group": "Moving Averages", "overlay": True,  "columns": ["ema_26"],                              "keys": ["value"]},
    # Bollinger Bands (overlay, three lines)
    {"id": "bb",       "label": "Bollinger Bands", "group": "Volatility",      "overlay": True,  "columns": ["bb_upper", "bb_middle", "bb_lower"],   "keys": ["upper", "middle", "lower"]},
    # MACD (panel, three lines)
    {"id": "macd",     "label": "MACD",            "group": "MACD",            "overlay": False, "columns": ["macd_line", "macd_signal", "macd_hist"], "keys": ["line", "signal", "hist"]},
    # Momentum (panel)
    {"id": "rsi_14",   "label": "RSI 14",          "group": "Momentum",        "overlay": False, "columns": ["rsi_14"],                              "keys": ["value"]},
    {"id": "stoch",    "label": "Stochastic",      "group": "Momentum",        "overlay": False, "columns": ["stoch_k", "stoch_d"],                  "keys": ["k", "d"]},
    {"id": "willr_14", "label": "Williams %R",     "group": "Momentum",        "overlay": False, "columns": ["willr_14"],                            "keys": ["value"]},
    {"id": "cci_20",   "label": "CCI 20",          "group": "Momentum",        "overlay": False, "columns": ["cci_20"],                              "keys": ["value"]},
    {"id": "mfi_14",   "label": "MFI 14",          "group": "Momentum",        "overlay": False, "columns": ["mfi_14"],                              "keys": ["value"]},
    {"id": "roc_10",   "label": "ROC 10",          "group": "Momentum",        "overlay": False, "columns": ["roc_10"],                              "keys": ["value"]},
    # Volatility (panel)
    {"id": "atr_14",   "label": "ATR 14",          "group": "Volatility",      "overlay": False, "columns": ["atr_14"],                              "keys": ["value"]},
    {"id": "natr_14",  "label": "NATR 14",         "group": "Volatility",      "overlay": False, "columns": ["natr_14"],                             "keys": ["value"]},
    # Trend / DMI (panel, multi-line)
    {"id": "adx",      "label": "ADX + DI",        "group": "Trend",           "overlay": False, "columns": ["adx_14", "plus_di_14", "minus_di_14"], "keys": ["adx", "plus_di", "minus_di"]},
    {"id": "aroon",    "label": "Aroon",           "group": "Trend",           "overlay": False, "columns": ["aroon_up_14", "aroon_down_14"],        "keys": ["up", "down"]},
    {"id": "sar",      "label": "Parabolic SAR",   "group": "Trend",           "overlay": True,  "columns": ["sar"],                                 "keys": ["value"]},
    # Volume
    {"id": "vwap",     "label": "VWAP",            "group": "Volume",          "overlay": True,  "columns": ["vwap"],                                "keys": ["value"]},
    {"id": "obv",      "label": "OBV",             "group": "Volume",          "overlay": False, "columns": ["obv"],                                 "keys": ["value"]},
    {"id": "ad",       "label": "A/D Line",        "group": "Volume",          "overlay": False, "columns": ["ad"],                                  "keys": ["value"]},
]

_INDICATOR_BY_ID: dict[str, dict[str, Any]] = {ind["id"]: ind for ind in _INDICATORS}

# Whitelist of all valid DB column names — guards dynamic SQL construction.
_ALLOWED_COLUMNS: frozenset[str] = frozenset(
    col for ind in _INDICATORS for col in ind["columns"]
)

_VALID_GRANULARITIES: frozenset[str] = frozenset(["15min", "1h", "1day", "1mo"])

_VALID_INSTRUMENT_TYPES: frozenset[str] = frozenset(["equity", "index"])


# ── Pydantic schemas ──────────────────────────────────────────────────────────

class IndicatorMeta(BaseModel):
    """Metadata for a single selectable technical indicator.

    Attributes:
        id:      Unique key used as the ``indicator`` query parameter.
        label:   Human-readable dropdown label.
        group:   Option-group category (Moving Averages, MACD, etc.).
        overlay: True when the indicator should be overlaid on the price chart.
        keys:    Field names present in each data-point dict.
    """

    id: str
    label: str
    group: str
    overlay: bool
    keys: list[str]


class IndicatorPoint(BaseModel):
    """Single time-series data point for an indicator.

    The ``values`` dict maps response ``keys`` (from :class:`IndicatorMeta`)
    to their numeric value, or ``None`` when the DB row holds NULL.

    Attributes:
        date:   ISO-8601 date/datetime string derived from ``bar_time``.
        values: Map of key → value, e.g. ``{"value": 150.5}`` or
                ``{"upper": 160.0, "middle": 152.0, "lower": 144.0}``.
    """

    date: str
    values: dict[str, float | None]


class IndicatorSeries(BaseModel):
    """Response envelope for a single indicator time series.

    Attributes:
        symbol:      Ticker symbol (upper-cased).
        granularity: Bar granularity (15min, 1h, 1day, 1mo).
        indicator:   Indicator id that was requested.
        meta:        Full indicator metadata record.
        data:        Chronologically ordered data points.
        all_null:    True when every data point contains only NULL values
                     (indicates missing data in the DB).
    """

    symbol: str
    granularity: str
    indicator: str
    meta: IndicatorMeta
    data: list[IndicatorPoint]
    all_null: bool


# ── Endpoints ────────────────────────────────────────────────────────────────

@router.get("/indicators", response_model=list[IndicatorMeta])
async def list_indicators() -> list[IndicatorMeta]:
    """Return the static registry of selectable technical indicators.

    Clients use this to populate the indicator dropdown without hard-coding
    any options in the UI.

    Returns:
        List of :class:`IndicatorMeta` objects ordered by group and label.
    """
    return [
        IndicatorMeta(
            id=ind["id"],
            label=ind["label"],
            group=ind["group"],
            overlay=ind["overlay"],
            keys=ind["keys"],
        )
        for ind in _INDICATORS
    ]


@router.get("/stats/{symbol}/{granularity}", response_model=IndicatorSeries)
async def get_indicator_stats(
    symbol: str,
    granularity: str,
    indicator: str = Query(..., description="Indicator id, e.g. 'sma_20', 'macd', 'bb'"),
    instrument_type: str = Query("equity", description="'equity' or 'index'"),
    limit: int = Query(500, ge=1, le=5000, description="Max number of bars to return"),
) -> IndicatorSeries:
    """Fetch a time-series for a single technical indicator from ``quant_stats``.

    Each request returns only the requested indicator columns — no bulk data
    upload is performed.  The frontend fires one request per indicator so that
    chart overlays load lazily.

    Args:
        symbol:          Ticker symbol (case-insensitive, normalised to upper-case).
        granularity:     Bar granularity: ``15min``, ``1h``, ``1day``, or ``1mo``.
        indicator:       Indicator id matching an entry in ``/quant/indicators``.
        instrument_type: ``'equity'`` (default) or ``'index'``.
        limit:           Maximum number of data points to return (default 500).

    Returns:
        :class:`IndicatorSeries` with ordered data points and ``all_null`` flag.

    Raises:
        404: Unknown indicator id or granularity.
        422: Validation error (handled by FastAPI).
    """
    symbol = symbol.upper()

    if granularity not in _VALID_GRANULARITIES:
        raise HTTPException(
            status_code=404,
            detail=f"Unknown granularity '{granularity}'. Valid: {sorted(_VALID_GRANULARITIES)}",
        )

    if instrument_type not in _VALID_INSTRUMENT_TYPES:
        raise HTTPException(
            status_code=422,
            detail=f"instrument_type must be one of {sorted(_VALID_INSTRUMENT_TYPES)}",
        )

    ind = _INDICATOR_BY_ID.get(indicator)
    if ind is None:
        raise HTTPException(
            status_code=404,
            detail=f"Unknown indicator '{indicator}'. Use GET /quant/indicators for valid ids.",
        )

    # Safety: verify every column is in the whitelist before building SQL.
    columns: list[str] = ind["columns"]
    for col in columns:
        if col not in _ALLOWED_COLUMNS:
            logger.error("Requested column '%s' is not in the allowed whitelist", col)
            raise HTTPException(status_code=500, detail="Internal configuration error.")

    keys: list[str] = ind["keys"]
    sql = OhlcvStatsSQL.get_indicator_series(columns) + f"\nLIMIT {int(limit)}"

    try:
        async with raw_conn() as conn:
            conn.row_factory = dict_row
            rows = await conn.execute(
                sql,
                {"symbol": symbol, "instrument_type": instrument_type, "granularity": granularity},
            )
            db_rows = await rows.fetchall()
    except Exception as exc:
        logger.error("quant stats query failed for %s/%s/%s: %s", symbol, granularity, indicator, exc)
        raise HTTPException(status_code=500, detail="Database query failed.")

    def _safe(v: Any) -> float | None:
        """Coerce DB value to float or None."""
        if v is None:
            return None
        try:
            f = float(v)
            return None if (f != f or abs(f) > 1e15) else f
        except (TypeError, ValueError):
            return None

    data: list[IndicatorPoint] = []
    any_non_null = False

    for row in db_rows:
        bar_time = row["bar_time"]
        date_str = bar_time.isoformat() if hasattr(bar_time, "isoformat") else str(bar_time)
        values: dict[str, float | None] = {}
        for col, key in zip(columns, keys):
            v = _safe(row.get(col))
            values[key] = v
            if v is not None:
                any_non_null = True
        data.append(IndicatorPoint(date=date_str, values=values))

    meta = IndicatorMeta(
        id=ind["id"],
        label=ind["label"],
        group=ind["group"],
        overlay=ind["overlay"],
        keys=keys,
    )

    return IndicatorSeries(
        symbol=symbol,
        granularity=granularity,
        indicator=indicator,
        meta=meta,
        data=data,
        all_null=not any_non_null,
    )


class CurrencyInfo(BaseModel):
    """Currency information for a traded symbol.

    Attributes:
        code:     ISO 4217 currency code, e.g. ``'USD'``.
        name:     Full currency name, e.g. ``'US Dollar'``.
        symbol:   Display symbol, e.g. ``'$'``, ``'€'``.
        decimals: Decimal places used for price display.
    """

    code: str
    name: str
    symbol: str
    decimals: int


@router.get("/symbol-currency/{symbol}", response_model=CurrencyInfo)
async def get_symbol_currency(symbol: str) -> CurrencyInfo:
    """Return the currency for a symbol derived from its recorded market region.

    Looks up the most recent ``region`` in ``quant_stats`` for the given symbol,
    then joins ``regions`` → ``currencies`` to return the full currency record.

    Args:
        symbol: Ticker symbol (case-insensitive, normalised to upper-case).

    Returns:
        :class:`CurrencyInfo` with code, name, display symbol, and decimal places.

    Raises:
        404: Symbol has no region data or no linked currency in the DB.
    """
    currency = await get_currency_for_symbol(symbol.upper())
    if currency is None:
        raise HTTPException(
            status_code=404,
            detail=f"No currency data found for symbol '{symbol.upper()}'.",
        )
    return CurrencyInfo(**currency)
