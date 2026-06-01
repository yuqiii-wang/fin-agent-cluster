"""calculate_ohlcv_stats — business logic for computing OHLCV technical indicators.

Accepts a structured OHLCV ``StatsRecord`` and computes a full suite of technical
indicators using ``pandas_ta``, then upserts all bar rows into the appropriate
``fin_markets.quant_*_stats`` table based on the resolved instrument type.

Instrument routing
------------------
``equity``        → ``quant_stats``            (OhlcvStatsSQL)
``index``         → ``quant_index_stats``       (IndexStatsSQL)
``crypto``        → ``quant_crypto_stats``      (CryptoStatsSQL)
``precious_metal``→ ``quant_precious_metal_stats`` (PreciousMetalStatsSQL)
``commodity``     → ``quant_commodity_stats``   (CommodityStatsSQL)

Indicators computed
-------------------
Moving averages: SMA 20/50/200, EMA 12/26
MACD (12/26/9): line, signal, histogram
Momentum: RSI-14, Stochastic %K/%D (14/3/3), Williams %R-14, CCI-20, MFI-14, ROC-10
Volatility: ATR-14, Bollinger Bands (20, 2σ), Normalized ATR-14
Trend / ADX family: ADX-14, +DI-14, -DI-14, Aroon Up/Down-14, Parabolic SAR
Volume / price-volume: VWAP, OBV, Chaikin A/D Line

Public exports
--------------
``CalculateOhlcvStatsInput``    — Pydantic input model.
``CalculateOhlcvStatsOutput``   — Pydantic output model.
``calculate_ohlcv_stats_handler`` — Celery-layer async handler function.
``PERIOD_TO_GRANULARITY``       — Period → granularity mapping constant.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import TYPE_CHECKING, Any

from pydantic import BaseModel, Field

if TYPE_CHECKING:
    import pandas as pd

from backend.db.postgres import raw_conn
from backend.db.postgres.queries.fin_markets_indexes import (
    derive_yf_exchange_from_ticker,
    get_primary_index_for_exchange,
    is_index_ticker,
)
from backend.db.postgres.queries.fin_markets_quant import (
    CommodityStatsSQL,
    CryptoStatsSQL,
    IndexStatsSQL,
    OhlcvStatsSQL,
    PreciousMetalStatsSQL,
)
from backend.langgraph.models.common_tasks.errors.codes import (
    STATS_TASK_CALC_ERROR,
    STATS_TASK_UNSUPPORTED_PERIOD,
)
from backend.quant.instrument_types import resolve_instrument_type
from backend.quant.stats import build_indicator_df, build_ohlcv_dataframe, safe_float, STATS_DATA_TYPE, STATS_VIEW_TYPE
from backend.resources.stats.models import OhlcvStatsMatrix, StatsRecord

logger = logging.getLogger(__name__)

# Map StatsRecord.period → quant_stats.granularity (CHECK constraint values).
# yfinance returns hourly bars for '1d', daily for '1w'/'1mo'/'3mo'/'2y', monthly for '1y'.
PERIOD_TO_GRANULARITY: dict[str, str] = {
    "1d": "5min",
    "1w": "1day",
    "1mo": "1day",
    "3mo": "1day",
    "1y": "1mo",
    "2y": "1day",
}

# Map the provider prefix in StatsRecord.id to the canonical source label.
_RECORD_ID_SOURCE_MAP: dict[str, str] = {
    "yf": "yfinance",
    "fmp": "fmp",
    "mock": "mock",
}

_STATS_SQL_MAP: dict[str, type] = {
    "index":          IndexStatsSQL,
    "crypto":         CryptoStatsSQL,
    "precious_metal": PreciousMetalStatsSQL,
    "commodity":      CommodityStatsSQL,
    "equity":         OhlcvStatsSQL,
}


# ---------------------------------------------------------------------------
# Input / output models
# ---------------------------------------------------------------------------


class CalculateOhlcvStatsInput(BaseModel):
    """Input for the calculate_ohlcv_stats handler.

    Attributes:
        stats_record:  OHLCV stats record from :class:`GetStatsOutput.stats_record`.
        from_cache:    When ``True``, skip pandas_ta recomputation and instead return the
                       count of already-existing rows in ``quant_stats``.
                       Set to ``True`` by the calling seq when ``data_type != 'ohlcv'``.
        data_type:     Payload category passed down from :attr:`GetStatsOutput.data_type`.
                       Used by the dispatcher to select the correct handler; the stock-stats
                       handler only processes ``'ohlcv'`` records.
    """

    stats_record: StatsRecord
    from_cache: bool = Field(default=False, description="Skip recomputation; read row count from DB.")
    data_type: str = Field(default=STATS_DATA_TYPE.OHLCV.value, description="Payload category: 'ohlcv', 'options', 'futures', etc.")


class CalculateOhlcvStatsOutput(BaseModel):
    """Output from the calculate_ohlcv_stats handler.

    Attributes:
        rows_upserted: Number of bar rows written to ``quant_stats``.
        symbol:        Ticker symbol.
        granularity:   Bar granularity stored (e.g. ``'5min'``, ``'1day'``).
        source:        Provider source label (e.g. ``'yfinance'``, ``'fmp'``).
        df_split:      OHLCV (+ sma_20/rsi_14 when available) in pandas split orient for CandleStick rendering.
        stats_views:   Ordered list of applicable stats view types for this task.
    """

    rows_upserted: int
    symbol: str
    granularity: str
    source: str
    df_split: dict[str, Any] = Field(default_factory=dict)
    stats_views: list[str] = Field(default_factory=lambda: [STATS_VIEW_TYPE.CANDLE_STICK.value])


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _source_from_record_id(record_id: str) -> str:
    """Extract the canonical source label from a StatsRecord ID.

    Args:
        record_id: StatsRecord identifier, e.g. ``'yf-AAPL-1d'``.

    Returns:
        Source label, e.g. ``'yfinance'``.  Falls back to the raw prefix when
        no mapping is found.
    """
    prefix = record_id.split("-")[0]
    return _RECORD_ID_SOURCE_MAP.get(prefix, prefix)


def _build_slim_df_split(df: "pd.DataFrame", *, with_indicators: bool) -> dict[str, Any]:
    """Build a slim df_split dict for CandleStick rendering.

    Args:
        df:              DataFrame with OHLCV columns, and optionally ``SMA_20``/``RSI_14``
                         when ``with_indicators`` is ``True``.
        with_indicators: When ``True``, include renamed ``sma_20``/``rsi_14`` columns.

    Returns:
        Dict with ``"index"`` (ISO-8601 date strings), ``"columns"``, ``"data"``
        in pandas split orient.
    """
    cols = ["open", "high", "low", "close", "volume"]
    slim = df[cols].copy()
    if with_indicators:
        if "SMA_20" in df.columns:
            slim["sma_20"] = df["SMA_20"]
        if "RSI_14" in df.columns:
            slim["rsi_14"] = df["RSI_14"]

    slim = slim.dropna(subset=["open", "high", "low", "close"], how="all")

    return {
        "index": [str(t)[:10] for t in slim.index],
        "columns": list(slim.columns),
        "data": [
            [safe_float(v) for v in row]
            for row in slim.itertuples(index=False)
        ],
    }


def _row_to_params(
    bar_time: datetime,
    row: "pd.Series",
    *,
    symbol: str,
    currency_code: str,
    source: str,
    granularity: str,
    index_code: str | None,
) -> dict:
    """Build the named-parameter dict for :attr:`OhlcvStatsSQL.UPSERT`.

    Args:
        bar_time:      UTC bar open timestamp.
        row:           Pandas Series containing OHLCV and indicator columns.
        symbol:        Ticker symbol.
        currency_code: ISO 4217 currency code.
        source:        Provider source label.
        granularity:   Bar granularity string.
        index_code:    Primary market index code or ``None``.

    Returns:
        Dict of named parameters ready for ``psycopg3`` execute with named-param style.
    """
    sar = safe_float(row.get("PSARl_0.02_0.2")) or safe_float(row.get("PSARs_0.02_0.2"))

    return {
        "symbol": symbol,
        "currency_code": currency_code,
        "source": source,
        "granularity": granularity,
        "bar_time": bar_time,
        "open": safe_float(row.get("open")),
        "high": safe_float(row.get("high")),
        "low": safe_float(row.get("low")),
        "close": safe_float(row.get("close")),
        "volume": safe_float(row.get("volume")) or 0.0,
        "trade_count": None,
        "sma_20": safe_float(row.get("SMA_20")),
        "sma_50": safe_float(row.get("SMA_50")),
        "sma_200": safe_float(row.get("SMA_200")),
        "ema_12": safe_float(row.get("EMA_12")),
        "ema_26": safe_float(row.get("EMA_26")),
        "macd_line": safe_float(row.get("MACD_12_26_9")),
        "macd_signal": safe_float(row.get("MACDs_12_26_9")),
        "macd_hist": safe_float(row.get("MACDh_12_26_9")),
        "rsi_14": safe_float(row.get("RSI_14")),
        "stoch_k": safe_float(row.get("STOCHk_14_3_3")),
        "stoch_d": safe_float(row.get("STOCHd_14_3_3")),
        "atr_14": safe_float(row.get("ATRr_14")),
        "bb_upper": safe_float(row.get("BBU_20_2.0")),
        "bb_middle": safe_float(row.get("BBM_20_2.0")),
        "bb_lower": safe_float(row.get("BBL_20_2.0")),
        "adx_14": safe_float(row.get("ADX_14")),
        "plus_di_14": safe_float(row.get("DMP_14")),
        "minus_di_14": safe_float(row.get("DMN_14")),
        "aroon_up_14": safe_float(row.get("AROONU_14")),
        "aroon_down_14": safe_float(row.get("AROOND_14")),
        "sar": sar,
        "willr_14": safe_float(row.get("WILLR_14")),
        "cci_20": safe_float(row.get("CCI_20_0.015")),
        "mfi_14": safe_float(row.get("MFI_14")),
        "roc_10": safe_float(row.get("ROC_10")),
        "natr_14": safe_float(row.get("NATR_14")),
        "vwap": safe_float(row.get("VWAP_D")),
        "obv": safe_float(row.get("OBV")),
        "ad": safe_float(row.get("AD")),
        "index_code": index_code,
    }


# ---------------------------------------------------------------------------
# Handler — Celery-layer business logic
# ---------------------------------------------------------------------------


async def calculate_ohlcv_stats_handler(payload: dict) -> dict:
    """Compute technical indicators for the OHLCV series and upsert to quant_stats.

    Args:
        payload: Serialised :class:`CalculateOhlcvStatsInput` dict.

    Returns:
        Serialised :class:`CalculateOhlcvStatsOutput` dict.

    Raises:
        ValueError: When the period is unsupported or the matrix is empty.
        Exception:  Propagated from pandas_ta or psycopg3 on computation/DB errors.
    """
    inp = CalculateOhlcvStatsInput.model_validate(payload)
    record = inp.stats_record
    symbol = record.symbol.upper()

    granularity = PERIOD_TO_GRANULARITY.get(record.period)
    if granularity is None:
        raise ValueError(
            f"[{STATS_TASK_UNSUPPORTED_PERIOD}] period={record.period!r} has no "
            f"supported granularity mapping."
        )

    source = _source_from_record_id(record.id)

    yf_exchange = derive_yf_exchange_from_ticker(symbol)
    primary_index = get_primary_index_for_exchange(yf_exchange)
    currency_code = primary_index.currency_code if primary_index else "USD"
    index_code = primary_index.code if primary_index else None

    # The actual transformation: validate the raw record content into an OHLCV
    # matrix. Fails here (not in get_stats) when the payload is not OHLCV-shaped.
    try:
        matrix = OhlcvStatsMatrix.model_validate(record.content)
    except Exception as exc:
        raise ValueError(
            f"[{STATS_TASK_CALC_ERROR}] invalid OHLCV content for symbol={symbol} "
            f"period={record.period}: {exc}"
        ) from exc

    _instrument_type = resolve_instrument_type(symbol, is_index=is_index_ticker(symbol))
    _stats_sql = _STATS_SQL_MAP.get(_instrument_type, OhlcvStatsSQL)

    # --- bypass path: return existing row count without recomputing indicators ---
    if inp.from_cache:
        async with raw_conn(readonly=True) as conn:
            cur = await conn.execute(
                _stats_sql.COUNT_BY_SYMBOL_GRANULARITY, (symbol, granularity)
            )
            count_row = await cur.fetchone()
        bypass_df_split: dict[str, Any] = {}
        if matrix.timestamps:
            ohlcv_df = build_ohlcv_dataframe(matrix)
            bypass_df_split = _build_slim_df_split(ohlcv_df, with_indicators=False)
        return CalculateOhlcvStatsOutput(
            rows_upserted=count_row["row_count"] if count_row else 0,
            symbol=symbol,
            granularity=granularity,
            source=source,
            df_split=bypass_df_split,
        ).model_dump()

    if not matrix.timestamps:
        raise ValueError(
            f"[{STATS_TASK_CALC_ERROR}] Empty OHLCV matrix for symbol={symbol} "
            f"period={record.period}"
        )

    # --- build DatetimeIndex DataFrame and compute all technical indicators ---
    try:
        df = build_ohlcv_dataframe(matrix)
        df = build_indicator_df(df)
    except Exception as exc:
        raise ValueError(
            f"[{STATS_TASK_CALC_ERROR}] Indicator computation failed for "
            f"symbol={symbol}: {exc}"
        ) from exc

    params_list = [
        _row_to_params(
            bar_time,
            row,
            symbol=symbol,
            currency_code=currency_code,
            source=source,
            granularity=granularity,
            index_code=index_code,
        )
        for bar_time, row in df.iterrows()
    ]

    async with raw_conn() as conn:
        for params in params_list:
            await conn.execute(_stats_sql.UPSERT, params)

    df_split = _build_slim_df_split(df, with_indicators=True)
    return CalculateOhlcvStatsOutput(
        rows_upserted=len(params_list),
        symbol=symbol,
        granularity=granularity,
        source=source,
        df_split=df_split,
        stats_views=[STATS_VIEW_TYPE.DATA_FRAME.value],
    ).model_dump()


__all__ = [
    "CalculateOhlcvStatsInput",
    "CalculateOhlcvStatsOutput",
    "calculate_ohlcv_stats_handler",
    "PERIOD_TO_GRANULARITY",
]
