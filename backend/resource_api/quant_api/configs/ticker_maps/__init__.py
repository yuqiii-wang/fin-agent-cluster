"""Per-provider TICKER_MAP configuration files.

Each sub-module exposes a single ``TICKER_MAP: dict[str, str | None]`` where:
  - A string value is the provider-specific symbol to use.
  - ``None`` means the provider cannot serve that ticker (client skips it).
  - Absence from the map means pass-through (canonical symbol used as-is).
"""
