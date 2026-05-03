"""FMP (Financial Modeling Prep) stats provider — transform FMP JSON into StatsRecord.

FMP returns JSON arrays from endpoints like:

``GET /historical-price-full/{symbol}?from=...&to=...&apikey=...``

Response shape::

    {
        "symbol": "AAPL",
        "historical": [
            {
                "date":             "2026-04-14",
                "open":             182.4,
                "high":             184.9,
                "low":              181.5,
                "close":            184.1,
                "volume":           71000000,
                "vwap":             183.5,
                "changePercent":    0.87,
                "change":           1.6,
                ...
            },
            ...
        ]
    }

The array is ordered newest-first from FMP; the transformer reverses to
chronological order (oldest-first) to match StatsMatrix convention.

Mapped series
-------------
FMP field        → StatsMatrix key
``open``         → ``open``
``high``         → ``high``
``low``          → ``low``
``close``        → ``close``
``volume``       → ``volume``
``vwap``         → ``vwap``          (included when present)
``changePercent``→ ``change_pct``    (included when present)

``GET /historical-chart/{interval}/{symbol}?apikey=...``
---------------------------------------------------------
For intraday data FMP returns a flat array (no ``"historical"`` wrapper)::

    [
        {"date": "2026-04-14 15:30:00", "open": 184.0, "high": 184.9,
         "low": 183.5, "close": 184.1, "volume": 1200000},
        ...
    ]

:func:`transform` handles both shapes automatically.
"""

from __future__ import annotations

from backend.resources.stats.models import StatsMatrix, StatsRecord

# FMP field name → StatsMatrix series key
_FIELD_MAP: dict[str, str] = {
    "open":          "open",
    "high":          "high",
    "low":           "low",
    "close":         "close",
    "volume":        "volume",
    "vwap":          "vwap",
    "changePercent": "change_pct",
}


def _record_id(symbol: str, period: str) -> str:
    """Generate a deterministic record ID from symbol + period."""
    return f"fmp-{symbol.lower()}-{period}"


def transform(
    symbol: str,
    period: str,
    raw: dict | list,
) -> StatsRecord:
    """Transform a FMP API response into a :class:`StatsRecord`.

    Accepts both the full ``/historical-price-full`` response dict (with a
    ``"historical"`` key) and the flat array returned by ``/historical-chart``.

    Args:
        symbol: Equity ticker used in the fetch, e.g. ``"AAPL"``.
        period: Aggregation period label, e.g. ``"1d"``.
        raw:    Parsed JSON response — either a ``dict`` with a
                ``"historical"`` list, or a bare ``list`` of bar dicts.

    Returns:
        A :class:`~backend.resources.stats.models.StatsRecord` with
        ``content.timestamps`` as the x-axis and each mapped field as a
        named series in ``content.series``.

    Raises:
        ValueError: If the response contains no data rows.
    """
    rows: list[dict] = _extract_rows(raw)
    if not rows:
        raise ValueError(f"FMP returned empty data for {symbol!r} period={period!r}")

    # FMP returns newest-first; reverse to chronological order
    rows = list(reversed(rows))

    timestamps: list[str] = [_parse_date(row["date"]) for row in rows]

    series: dict[str, list[float]] = {}
    for fmp_field, series_key in _FIELD_MAP.items():
        values = [row.get(fmp_field) for row in rows]
        if all(v is None for v in values):
            continue
        series[series_key] = [float(v) if v is not None else 0.0 for v in values]

    if not series:
        raise ValueError(f"No recognisable OHLCV fields in FMP response for {symbol!r}")

    return StatsRecord(
        id=_record_id(symbol, period),
        symbol=symbol.upper(),
        period=period,
        content=StatsMatrix(timestamps=timestamps, series=series),
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _extract_rows(raw: dict | list) -> list[dict]:
    """Extract the list of bar dicts from either FMP response shape.

    Args:
        raw: Full ``/historical-price-full`` dict or flat ``/historical-chart`` list.

    Returns:
        List of individual bar dicts.
    """
    if isinstance(raw, list):
        return raw
    # Full endpoint: {"symbol": "...", "historical": [...]}
    return raw.get("historical", [])


def _parse_date(value: str) -> str:
    """Normalise a FMP date string to an ISO-8601 date (``YYYY-MM-DD``).

    FMP daily bars use ``"2026-04-14"``; intraday bars use
    ``"2026-04-14 15:30:00"``.  This function strips the time component
    when present.

    Args:
        value: Raw FMP date string.

    Returns:
        ``"YYYY-MM-DD"`` string.
    """
    return value[:10]
