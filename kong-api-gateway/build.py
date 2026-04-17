#!/usr/bin/env python3
"""Merge Kong declarative config fragments into kong.yml.

Kong DB-less mode (KONG_DATABASE=off) loads exactly one file at startup via
KONG_DECLARATIVE_CONFIG.  Variable substitution is NOT supported in kong.yml
(only in kong.conf), so this script resolves all {PLACEHOLDER} tokens using
environment variables (with fallback defaults) before writing the output file.

Usage (from project root):

    python kong-api-gateway/build.py

    # Override defaults via environment:
    BACKEND_HOST=192.168.1.10 BACKEND_PORT=9000 python kong-api-gateway/build.py

Directory layout (mirrors FastAPI routing paths):

    kong-api-gateway/
      _shared/
        base.yml            # _format_version, _transform
        upstreams.yml       # fastapi-upstream definition
        services.yml        # fastapi + llm-proxy service stubs
        plugins.yml         # global plugins (CORS, rate-limit, …)
        dev_routes.yml      # /docs /redoc (remove in production)
      api/
        v1/
          auth/routes.yml   # POST /api/v1/auth/*
          users/routes.yml  # POST|GET /api/v1/users/query/*
          stream/routes.yml # GET /api/v1/stream/* (SSE)
          reports/routes.yml
          tasks/routes.yml
          quant/routes.yml
      llm/
        routes.yml          # POST /llm/* (Kong AI Gateway)
        plugins.yml         # ai-proxy plugin scoped to llm-proxy service

Merge order:
  1. _shared/base.yml
  2. _shared/upstreams.yml
  3. _shared/services.yml
  4. api/v1/**/*.yml  (sorted by path)
  5. llm/**/*.yml     (sorted by filename — routes before plugins)
  6. _shared/plugins.yml   (global — appended last so they apply everywhere)
  7. _shared/dev_routes.yml
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import yaml

GATEWAY_DIR = Path(__file__).resolve().parent
OUTPUT = GATEWAY_DIR / "kong.yml"

# Default values for all placeholders used in source fragments.
# Override any value by setting the corresponding environment variable before
# running this script, e.g.:  BACKEND_HOST=10.0.0.5 python build.py
_DEFAULTS: dict[str, str] = {
    "BACKEND_HOST": "host.docker.internal",
    "BACKEND_PORT": "8432",
    "OLLAMA_HOST": "host.docker.internal",
    "OLLAMA_PORT": "11434",
    "OLLAMA_MODEL": "qwen3.5-27b",
}

# List-valued Kong keys — fragments are concatenated across files.
_LIST_KEYS: frozenset[str] = frozenset(
    {"upstreams", "services", "routes", "plugins", "consumers", "certificates"}
)
# Scalar Kong keys — first file wins (_shared/base.yml sets these).
_SCALAR_KEYS: frozenset[str] = frozenset({"_format_version", "_transform"})


def _resolve_vars(text: str) -> str:
    """Substitute {PLACEHOLDER} tokens in *text* using env vars with fallback defaults.

    Reads each placeholder from the environment first; falls back to
    ``_DEFAULTS`` if the variable is unset or empty.

    Args:
        text: Raw fragment text that may contain ``{VAR}`` tokens.

    Returns:
        Text with all known placeholders replaced by their resolved values.
    """
    mapping = {k: os.environ.get(k) or v for k, v in _DEFAULTS.items()}
    for key, value in mapping.items():
        text = text.replace(f"{{{key}}}", value)
    return text


def _scan_order() -> list[Path]:
    """Return fragment files in deterministic merge order.

    Returns:
        Ordered list of YAML fragment paths to merge.
    """
    order: list[Path] = [
        GATEWAY_DIR / "_shared" / "base.yml",
        GATEWAY_DIR / "_shared" / "upstreams.yml",
        GATEWAY_DIR / "_shared" / "services.yml",
    ]

    # api/v1/** — walk alphabetically so auth < quant < reports < stream < tasks < users
    api_dir = GATEWAY_DIR / "api" / "v1"
    if api_dir.exists():
        for fragment in sorted(api_dir.rglob("*.yml")):
            order.append(fragment)

    # llm/ — routes before plugins within the directory
    llm_dir = GATEWAY_DIR / "llm"
    if llm_dir.exists():
        for fragment in sorted(llm_dir.glob("*.yml")):
            order.append(fragment)

    # Global plugins and dev routes always come last
    order.append(GATEWAY_DIR / "_shared" / "plugins.yml")
    order.append(GATEWAY_DIR / "_shared" / "dev_routes.yml")
    return order


def _merge(base: dict[str, Any], overlay: dict[str, Any]) -> dict[str, Any]:
    """Merge *overlay* into *base* in-place and return *base*.

    Rules:
    - Scalar keys (``_format_version``, ``_transform``): first writer wins.
    - List keys (``upstreams``, ``services``, ``routes``, ``plugins``, …):
      overlay list is appended to base list.
    - Any other key: overlay value overwrites base value.

    Args:
        base:    Accumulator dict modified in-place.
        overlay: Fragment dict to merge in.

    Returns:
        The modified *base* dict.
    """
    for key, value in overlay.items():
        if key in _SCALAR_KEYS:
            base.setdefault(key, value)
        elif key in _LIST_KEYS:
            base.setdefault(key, [])
            if isinstance(value, list):
                base[key].extend(value)
        else:
            base[key] = value
    return base


def build() -> None:
    """Merge all fragments into ``kong.yml`` and write the output file."""
    # Show resolved variable values so the operator can verify them.
    resolved = {k: os.environ.get(k) or v for k, v in _DEFAULTS.items()}
    print("Variables resolved:")
    for k, v in resolved.items():
        source = "env" if os.environ.get(k) else "default"
        print(f"  {k}={v}  ({source})")
    print()

    merged: dict[str, Any] = {}

    for path in _scan_order():
        if not path.exists():
            print(f"  skip  {path.relative_to(GATEWAY_DIR)}")
            continue
        with path.open(encoding="utf-8") as fh:
            data: dict[str, Any] = yaml.safe_load(_resolve_vars(fh.read())) or {}
        _merge(merged, data)
        print(f"  merge {path.relative_to(GATEWAY_DIR)}")

    header = (
        "# AUTO-GENERATED — do not edit directly.\n"
        "# Run:  python kong-api-gateway/build.py\n"
        "#\n"
        "# Source fragments:\n"
        "#   _shared/          upstreams, services, global plugins\n"
        "#   api/v1/auth/      POST /api/v1/auth/*\n"
        "#   api/v1/users/     POST|GET /api/v1/users/query/*\n"
        "#   api/v1/stream/    GET /api/v1/stream/* (SSE)\n"
        "#   api/v1/reports/   GET /api/v1/reports/*\n"
        "#   api/v1/tasks/     GET|POST /api/v1/tasks/*\n"
        "#   api/v1/quant/     GET /api/v1/quant/*\n"
        "#   llm/              POST /llm/* (Kong AI Gateway ai-proxy)\n"
        "\n"
    )

    with OUTPUT.open("w", encoding="utf-8") as fh:
        fh.write(header)
        yaml.dump(merged, fh, default_flow_style=False, allow_unicode=True, sort_keys=False)

    print(f"\nWrote → {OUTPUT}")


if __name__ == "__main__":
    build()
