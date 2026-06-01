"""Parser utilities for financial option data extraction and conversion.

Provides functions to parse and convert option chain data values:
- Extract numbers from markdown links
- Handle negative numbers
- Convert percentages to decimals
- Handle empty/None values
"""

from __future__ import annotations

import re
from typing import Any

from backend.quant.stats import safe_float


def extract_value(input_val: Any) -> str | None:
    """Extract the core value from a string, handling markdown links.

    Args:
        input_val: Raw input value (string, int, float, None)

    Returns:
        Extracted string value or None
    """
    if input_val is None:
        return None
    if not isinstance(input_val, str):
        return str(input_val)

    # Extract content inside [...] if it's a markdown link
    match = re.match(r'\[([^\]]+)\]', input_val)
    if match:
        return match.group(1)

    return input_val.strip()


def parse_numeric_value(input_val: Any) -> float | None:
    """Parse a value to a float, handling special cases.

    Args:
        input_val: Raw input value

    Returns:
        Float value or None
    """
    extracted = extract_value(input_val)

    if extracted is None:
        return None

    # Handle single '-' as None
    if extracted == '-':
        return None

    # Remove commas from numbers (e.g., 1,000 -> 1000)
    cleaned = extracted.replace(',', '')

    # Check for percentage
    is_percent = '%' in cleaned
    if is_percent:
        cleaned = cleaned.replace('%', '').strip()

    # Convert to float
    num = safe_float(cleaned)

    if num is not None and is_percent:
        num = num / 100.0

    return num


def parse_integer_value(input_val: Any) -> int | None:
    """Parse a value to an integer, handling special cases.

    Args:
        input_val: Raw input value

    Returns:
        Integer value or None
    """
    num = parse_numeric_value(input_val)
    return int(num) if num is not None and num.is_integer() else None


def parse_percent_value(input_val: Any) -> float | None:
    """Parse a percentage value to a decimal.

    Args:
        input_val: Raw input value (e.g., "50.00%", "0.00%")

    Returns:
        Decimal value (e.g., 0.50, 0.00) or None
    """
    return parse_numeric_value(input_val)


def parse_contract_name_from_link(input_val: Any) -> str | None:
    """Extract contract name from a markdown link.

    Args:
        input_val: Raw input value (e.g., "[AAPL260601P00225000](/quote/...)")

    Returns:
        Contract name string or None
    """
    return extract_value(input_val)


__all__ = [
    'extract_value',
    'parse_numeric_value',
    'parse_integer_value',
    'parse_percent_value',
    'parse_contract_name_from_link',
]
