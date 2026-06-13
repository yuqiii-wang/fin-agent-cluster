"""extraction_schema.py -- Shared objective, output schema and extraction rules
for the prepare_derivatives web-knowledge steps (``load_markdown`` + ``study_web``)."""

from __future__ import annotations

NAVIGATE_OBJECTIVE: str = (
    "Find options chain, derivatives contracts, and related market data for the equity symbol {symbol}."
)

_CONTRACT_SCHEMA: dict = {
    "type": "object",
    "properties": {
        "contract_name": {
            "type": "string",
            "description": "Full OSI symbol, e.g. 'AAPL260529C00150000'.",
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
    "required": ["contract_name", "strike"],
}

DERIVATIVES_OUTPUT_SCHEMA: dict = {
    "type": "object",
    "properties": {
        "symbol": {
            "type": "string",
            "description": "Equity symbol for which the options were extracted.",
        },
        "expiration_date": {
            "type": "string",
            "description": "Expiration date of the options contracts.",
        },
        "calls": {
            "type": "array",
            "description": "List of call contracts extracted from the options chain.",
            "items": _CONTRACT_SCHEMA,
        },
        "puts": {
            "type": "array",
            "description": "List of put contracts extracted from the options chain.",
            "items": _CONTRACT_SCHEMA,
        },
    },
    "required": ["calls", "puts"],
}

ADDITIONAL_CONTEXT: list[str] = [
    "Output two separate lists: 'calls' for call contracts and 'puts' for put contracts. "
    "Every entry must include contract_name (OSI format, e.g. AAPL260601C00150000) and strike. "
    "If the page contains no extractable contracts, output empty lists for 'calls' and 'puts'.",
    "FIELD EXTRACTION -- many table cells contain markdown hyperlinks; extract only the "
    "visible label text, never the URL. "
    "Examples: "
    "'[AAPL260601C00250000](/quote/AAPL260601C00250000/)' -> contract_name = 'AAPL260601C00250000'; "
    "'[250](/quote/AAPL/options/?straddle=false&strike=250&type=all)' -> strike = 250. "
    "NUMERIC FIELDS -- strip any trailing '%' and return a plain number: "
    "'32.32%' -> pct_change = 32.32; '145.31%' -> implied_volatility = 145.31. "
    "DATE FIELDS -- copy the date/time string as-is, e.g. '5/29/2026 1:16 PM'.",
]

__all__ = [
    "NAVIGATE_OBJECTIVE",
    "DERIVATIVES_OUTPUT_SCHEMA",
    "ADDITIONAL_CONTEXT",
]
