"""field_name_conversion -- generic field-name normalisation utilities.

Converts arbitrary naming conventions to ``snake_case`` without hardcoding
any specific field names.

Supported input conventions
---------------------------
- ``PascalCase``        -> ``ContractName``
- ``camelCase``         -> ``contractName``
- ``Title Case``        -> ``Contract Name``
- ``SCREAMING_SNAKE``   -> ``CONTRACT_NAME``
- ``SCREAMING SPACE``   -> ``CONTRACT NAME``
- ``kebab-case``        -> ``contract-name``
- ``space separated``   -> ``contract name``

All of the above produce ``contract_name``.

Public exports
--------------
``to_snake_case``  -- convert a single string to snake_case.
``normalize_keys`` -- return a shallow copy of a dict with all string keys normalised.
``coerce_numeric`` -- coerce a raw value (including percent strings) to ``float``.
"""

from __future__ import annotations

import math
import re

__all__ = ["to_snake_case", "normalize_keys", "coerce_numeric"]


def to_snake_case(name: str) -> str:
    """Convert any naming convention string to ``snake_case``.

    The conversion is purely structural -- no specific field names are hardcoded.
    The four-step algorithm handles the most common naming conventions:

    1. Insert ``_`` between a lowercase letter / digit and an uppercase letter
       (camelCase / PascalCase boundary: ``contractName`` -> ``contract_Name``).
    2. Insert ``_`` before an ``UpperLower`` pair that follows consecutive uppercase
       letters (e.g. ``ABCDef`` -> ``ABC_Def``).
    3. Replace spaces, hyphens, and dots with ``_``.
    4. Collapse consecutive underscores; strip leading / trailing underscores.

    Args:
        name: A field name in any conventional form.

    Returns:
        The snake_case equivalent, e.g. ``'contract_name'``.

    Examples::

        to_snake_case("ContractName")     # -> 'contract_name'
        to_snake_case("CONTRACT NAME")    # -> 'contract_name'
        to_snake_case("contract-name")    # -> 'contract_name'
        to_snake_case("Contract_Name")    # -> 'contract_name'
        to_snake_case("impliedVolatility") # -> 'implied_volatility'
        to_snake_case("ABCDef")           # -> 'abc_def'
    """
    # Step 1: lowercase-to-uppercase transition (camelCase / PascalCase).
    s = re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", name)
    # Step 2: consecutive uppercase followed by an UpperLower pair (e.g. ABCDef -> ABC_Def).
    s = re.sub(r"([A-Z]+)([A-Z][a-z])", r"\1_\2", s)
    # Step 3: spaces, hyphens, and dots become underscores.
    s = re.sub(r"[\s\-\.]+", "_", s)
    # Step 4: collapse duplicates; strip boundary underscores.
    s = re.sub(r"_+", "_", s).strip("_")
    return s.lower()


def normalize_keys(d: dict) -> dict:
    """Return a shallow copy of *d* with every string key converted to snake_case.

    Non-string keys are preserved unchanged.  Values are never mutated.

    Args:
        d: Source dictionary whose keys may use any naming convention.

    Returns:
        New dict with snake_case keys and the original values.

    Examples::

        normalize_keys({"ContractName": "AAPL260601C00200000", "Strike": 200.0})
        # -> {"contract_name": "AAPL260601C00200000", "strike": 200.0}
    """
    return {to_snake_case(k) if isinstance(k, str) else k: v for k, v in d.items()}


def coerce_numeric(val: object) -> float:
    """Coerce a raw field value to ``float``, returning ``0.0`` on failure.

    Handles the common data variations encountered in scraped options-chain payloads:

    - Plain ``int`` / ``float``          -> ``float(val)``
    - Percent strings                    -> ``'107.81%'``  -> ``107.81``
    - Numeric strings                    -> ``'250.00'``   -> ``250.0``
    - ``None`` / ``bool`` / non-numeric  -> ``0.0``
    - Non-finite (NaN / Inf)             -> ``0.0``

    Args:
        val: Raw value from an un-typed data dict.

    Returns:
        Coerced finite float; ``0.0`` when conversion is impossible.
    """
    if isinstance(val, bool):
        return 0.0
    if isinstance(val, (int, float)):
        try:
            f = float(val)
            return f if math.isfinite(f) else 0.0
        except (TypeError, ValueError):
            return 0.0
    if isinstance(val, str):
        stripped = val.strip().rstrip("%").strip()
        try:
            f = float(stripped)
            return f if math.isfinite(f) else 0.0
        except ValueError:
            return 0.0
    return 0.0
