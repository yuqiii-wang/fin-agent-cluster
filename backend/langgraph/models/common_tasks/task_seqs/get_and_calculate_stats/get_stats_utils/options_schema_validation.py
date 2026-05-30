"""options_schema_validation — per-contract validation for the flat options json_input.

Implements structural validation for the canonical flat-``options`` format that
matches ``_DERIVATIVES_OUTPUT_SCHEMA`` in the ``prepare_derivatives`` navigate_web step::

    {
        "data_type": "options",
        "options": [
            {"contract_name": "AAPL260601C00150000", "options_type": "call", "strike": 150.0, ...},
            ...
        ]
    }

Each contract entry is validated against the mandatory fields required by
:class:`~calculation_utils.calculate_option_stats.CalculateOptionStatsInput`.

Public exports
--------------
``validate_options`` — raises ``ValueError`` with an error code prefix on any violation.
"""

from __future__ import annotations

from typing import Any

from backend.langgraph.models.common_tasks.errors.codes import STATS_TASK_JSON_INPUT_INVALID


def validate_options(data: dict[str, Any]) -> None:
    """Validate an options-chain json_input payload (flat options format).

    The canonical format uses a flat ``options`` list where every entry is a
    contract dict with at minimum ``contract_name``, ``options_type``, and ``strike``.
    This matches the ``_DERIVATIVES_OUTPUT_SCHEMA`` produced by the
    ``prepare_derivatives`` navigate_web sandbox step.

    Args:
        data: Full json_input dict (``data_type`` already confirmed as ``"options"``).

    Raises:
        ValueError: On any schema violation.
    """
    options: list = data.get("options") or []
    if not isinstance(options, list) or not options:
        raise ValueError(
            f"[{STATS_TASK_JSON_INPUT_INVALID}] options json_input requires a non-empty "
            f"'options' list.  "
            f"Each entry must include 'contract_name' (OSI format, e.g. AAPL260601C00150000), "
            f"'options_type' ('call' or 'put'), and 'strike'."
        )

    for idx, contract in enumerate(options):
        if not isinstance(contract, dict):
            raise ValueError(
                f"[{STATS_TASK_JSON_INPUT_INVALID}] options json_input options[{idx}] "
                f"must be a dict; got {type(contract).__name__!r}."
            )
        for field in ("contract_name", "options_type"):
            if not contract.get(field):
                raise ValueError(
                    f"[{STATS_TASK_JSON_INPUT_INVALID}] options json_input "
                    f"options[{idx}] is missing required field '{field}'."
                )
        if contract.get("strike") in (None, ""):
            raise ValueError(
                f"[{STATS_TASK_JSON_INPUT_INVALID}] options json_input "
                f"options[{idx}] is missing required field 'strike'."
            )


__all__ = ["validate_options"]
