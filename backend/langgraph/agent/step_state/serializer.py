"""serializer.py — Convert agent state objects to JSON-safe dicts.

Handles the common case of nested dataclasses, Pydantic BaseModel instances,
lists, and plain dicts that appear in agent global/step states.  Any value
that cannot be serialised natively is coerced to ``str``.
"""

from __future__ import annotations

import dataclasses
from typing import Any


def to_json_safe(obj: Any) -> dict[str, Any]:
    """Recursively convert *obj* to a plain ``dict`` safe for ``json.dumps``.

    Priority order:
    1. ``None`` → ``{}``
    2. Pydantic ``BaseModel`` → ``.model_dump(mode="json")``
    3. ``dataclass`` → ``dataclasses.fields`` recursion
    4. ``dict`` → recurse values
    5. ``list`` / ``tuple`` → recurse elements (returned inside ``{"items": [...]}``
       only when called at top level; nested lists are kept as lists)
    6. Fallback → ``str(obj)``

    Args:
        obj: Any value produced by a concrete agent node's global/step state.

    Returns:
        A ``dict[str, Any]`` where all leaf values are JSON primitives or strings.
    """
    return _convert(obj, top_level=True)  # type: ignore[return-value]


def _convert(obj: Any, top_level: bool = False) -> Any:
    if obj is None:
        return {} if top_level else None

    # Pydantic v2
    try:
        from pydantic import BaseModel  # local to avoid circular at module level
        if isinstance(obj, BaseModel):
            return obj.model_dump(mode="json")
    except ImportError:
        pass

    if dataclasses.is_dataclass(obj) and not isinstance(obj, type):
        return {
            f.name: _convert(getattr(obj, f.name))
            for f in dataclasses.fields(obj)
        }

    if isinstance(obj, dict):
        return {str(k): _convert(v) for k, v in obj.items()}

    if isinstance(obj, (list, tuple)):
        converted = [_convert(item) for item in obj]
        if top_level:
            return {"items": converted}
        return converted

    # Primitives
    if isinstance(obj, (str, int, float, bool)):
        return obj  # type: ignore[return-value]

    # Fallback: coerce to string so serialisation never raises.
    return str(obj)


__all__ = ["to_json_safe"]
