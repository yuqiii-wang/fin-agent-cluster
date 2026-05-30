"""json_input_validation — schema validation for structured json_input in get_stats.

Every caller that supplies ``json_input`` to :class:`GetStatsInput` must include a
``data_type`` discriminator.  This module validates the rest of the payload against
the mandatory fields required by the downstream calculation handlers.

Supported data types and their required fields
----------------------------------------------
``"ohlcv"``
    Direct OHLCV time-series, processed by
    :func:`~calculation_utils.calculate_stock_stats.calculate_stock_stats_handler`.

    Required:
        ``timestamps``       — non-empty list of ISO-8601 date/datetime strings.
        ``series``           — dict containing at minimum ``"open"``, ``"high"``,
                               ``"low"``, ``"close"``; each a list of numbers whose
                               length matches ``timestamps``.

``"options"``
    Options-chain snapshot, processed by
    :func:`~calculation_utils.calculate_option_stats`.

    Canonical flat format (matches ``_DERIVATIVES_OUTPUT_SCHEMA``)::

        {"data_type": "options", "options": [{"contract_name": "AAPL260601C00150000", ...}, ...]}

    Required per contract dict:
        ``contract_name``  — OSI option symbol string (e.g. ``"AAPL260601C00150000"``).
        ``options_type``   — ``"call"`` / ``"put"``.
        ``strike``         — numeric strike price.

``"fundamentals"``
    Multi-endpoint fundamental financial data, processed by
    :func:`~calculation_utils.calculate_fundamental_stats.calculate_fundamental_stats_handler`.

    Required:
        ``items``            — non-empty list of endpoint dicts.
        Each item dict must contain:
            ``endpoint_type``  — one of ``"income_statement"``, ``"balance_sheet"``,
                                  ``"cash_flow"``, ``"key_metrics"``.
            ``json_data``      — non-empty dict with at least one field recognised by
                                  the field normalisation map.

``"futures"``
    Not yet implemented; raises immediately.

Public exports
--------------
``validate_json_input`` — entry-point validation function; raises ``ValueError``
                          with an error code prefix on any schema violation.
"""

from __future__ import annotations

from typing import Any

from backend.langgraph.models.common_tasks.errors.codes import (
    STATS_TASK_JSON_INPUT_INVALID,
    STATS_TASK_JSON_INPUT_UNSUPPORTED_TYPE,
)
from backend.langgraph.models.common_tasks.task_seqs.get_and_calculate_stats.get_stats_utils.options_schema_validation import (
    validate_options,
)

# Valid endpoint types for fundamentals items.
_VALID_FUNDAMENTAL_ENDPOINT_TYPES: frozenset[str] = frozenset(
    {"income_statement", "balance_sheet", "cash_flow", "key_metrics"}
)

# Canonical fundamental field keys recognised by the field normalisation map in
# calculate_fundamental_stats.  At least one must be present in json_data.
_RECOGNISED_FUNDAMENTAL_KEYS: frozenset[str] = frozenset(
    {
        "revenue", "revenueGrowth", "grossProfit", "grossProfits",
        "operatingIncome", "netIncome",
        "epsdiluted", "eps", "trailingEps",
        "totalDebt", "totalStockholdersEquity", "totalStockholderEquity",
        "freeCashFlow", "freeCashflow",
        "peRatioTTM", "peRatio", "trailingPE",
        "forwardPERatioTTM", "forwardPE",
        "evToEbitdaTTM", "enterpriseValueOverEBITDA", "enterpriseToEbitda",
        "marketCapTTM", "marketCap",
        "dividendPerShareTTM", "dividendPerShare", "dividendRate",
    }
)

# Mandatory OHLCV series keys.
_REQUIRED_OHLCV_SERIES: frozenset[str] = frozenset({"open", "high", "low", "close"})


def _validate_ohlcv(data: dict[str, Any]) -> None:
    """Validate an OHLCV json_input payload.

    Args:
        data: Full json_input dict (``data_type`` already confirmed as ``"ohlcv"``).

    Raises:
        ValueError: On any schema violation.
    """
    timestamps = data.get("timestamps")
    if not isinstance(timestamps, list) or len(timestamps) == 0:
        raise ValueError(
            f"[{STATS_TASK_JSON_INPUT_INVALID}] ohlcv json_input requires a non-empty "
            f"'timestamps' list; got {type(timestamps).__name__!r}."
        )

    series = data.get("series")
    if not isinstance(series, dict) or len(series) == 0:
        raise ValueError(
            f"[{STATS_TASK_JSON_INPUT_INVALID}] ohlcv json_input requires a non-empty "
            f"'series' dict; got {type(series).__name__!r}."
        )

    missing = _REQUIRED_OHLCV_SERIES - series.keys()
    if missing:
        raise ValueError(
            f"[{STATS_TASK_JSON_INPUT_INVALID}] ohlcv json_input 'series' is missing "
            f"required keys: {sorted(missing)}.  "
            f"Required: {sorted(_REQUIRED_OHLCV_SERIES)}."
        )

    n = len(timestamps)
    for key in _REQUIRED_OHLCV_SERIES:
        col = series[key]
        if not isinstance(col, list):
            raise ValueError(
                f"[{STATS_TASK_JSON_INPUT_INVALID}] ohlcv json_input series['{key}'] "
                f"must be a list; got {type(col).__name__!r}."
            )
        if len(col) != n:
            raise ValueError(
                f"[{STATS_TASK_JSON_INPUT_INVALID}] ohlcv json_input series['{key}'] "
                f"has {len(col)} elements but 'timestamps' has {n}."
            )


def _validate_options(data: dict[str, Any]) -> None:
    """Validate an options-chain json_input payload (flat options format).

    Delegates to :func:`~options_schema_validation.validate_options` which
    validates the canonical flat ``options`` list matching
    ``_DERIVATIVES_OUTPUT_SCHEMA``.

    Args:
        data: Full json_input dict (``data_type`` already confirmed as ``"options"``).

    Raises:
        ValueError: On any schema violation.
    """
    validate_options(data)


def _validate_fundamentals(data: dict[str, Any]) -> None:
    """Validate a fundamentals json_input payload.

    Args:
        data: Full json_input dict (``data_type`` already confirmed as ``"fundamentals"``).

    Raises:
        ValueError: On any schema violation.
    """
    items = data.get("items")
    if not isinstance(items, list) or len(items) == 0:
        raise ValueError(
            f"[{STATS_TASK_JSON_INPUT_INVALID}] fundamentals json_input requires a "
            f"non-empty 'items' list; got {type(items).__name__!r}."
        )

    for idx, item in enumerate(items):
        if not isinstance(item, dict):
            raise ValueError(
                f"[{STATS_TASK_JSON_INPUT_INVALID}] fundamentals json_input items[{idx}] "
                f"must be a dict; got {type(item).__name__!r}."
            )
        endpoint_type = item.get("endpoint_type")
        if endpoint_type not in _VALID_FUNDAMENTAL_ENDPOINT_TYPES:
            raise ValueError(
                f"[{STATS_TASK_JSON_INPUT_INVALID}] fundamentals json_input items[{idx}] "
                f"'endpoint_type' must be one of {sorted(_VALID_FUNDAMENTAL_ENDPOINT_TYPES)}; "
                f"got {endpoint_type!r}."
            )
        json_data = item.get("json_data")
        if not isinstance(json_data, dict) or len(json_data) == 0:
            raise ValueError(
                f"[{STATS_TASK_JSON_INPUT_INVALID}] fundamentals json_input items[{idx}] "
                f"'json_data' must be a non-empty dict; got {type(json_data).__name__!r}."
            )
        recognised = set(json_data.keys()) & _RECOGNISED_FUNDAMENTAL_KEYS
        if not recognised:
            raise ValueError(
                f"[{STATS_TASK_JSON_INPUT_INVALID}] fundamentals json_input items[{idx}] "
                f"'json_data' contains no recognised fundamental fields.  "
                f"Expected at least one of: {sorted(_RECOGNISED_FUNDAMENTAL_KEYS)}."
            )


def validate_json_input(json_input: dict[str, Any]) -> None:
    """Validate the structured json_input dict against the mandatory fields for its data_type.

    Callers must include a ``data_type`` discriminator field.  Downstream tasks will
    fail with ambiguous errors if required fields are absent; this validation provides
    a clear early-failure message that llm_orchestration can act on.

    Supported data types: ``"ohlcv"``, ``"options"``, ``"fundamentals"``.
    ``"futures"`` is not yet implemented and raises immediately.

    Args:
        json_input: The raw dict supplied as :attr:`GetStatsInput.json_input`.

    Raises:
        ValueError: When ``data_type`` is missing, unsupported, or required fields
                    for the declared type are absent or malformed.
    """
    data_type = json_input.get("data_type")
    if not data_type:
        raise ValueError(
            f"[{STATS_TASK_JSON_INPUT_INVALID}] json_input must include a 'data_type' "
            f"field.  Supported values: 'ohlcv', 'options', 'fundamentals'."
        )

    if data_type == "ohlcv":
        _validate_ohlcv(json_input)
    elif data_type == "options":
        _validate_options(json_input)
    elif data_type == "fundamentals":
        _validate_fundamentals(json_input)
    elif data_type == "futures":
        raise ValueError(
            f"[{STATS_TASK_JSON_INPUT_UNSUPPORTED_TYPE}] json_input data_type='futures' "
            f"is not yet implemented."
        )
    else:
        raise ValueError(
            f"[{STATS_TASK_JSON_INPUT_INVALID}] Unknown json_input data_type={data_type!r}.  "
            f"Supported values: 'ohlcv', 'options', 'fundamentals'."
        )


__all__ = ["validate_json_input"]
