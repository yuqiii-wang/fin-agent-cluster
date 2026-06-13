"""Resource API error code registry.

Covers errors raised by the news and quant provider client chains.

Error code prefixes
-------------------
``RAPI_``   -- Resource API layer failures (provider chains, config, method dispatch).
"""

from __future__ import annotations

# ---------------------------------------------------------------------------
# Error code constants
# ---------------------------------------------------------------------------

#: A provider returned no data for the requested symbol / query (soft miss).
RAPI_PROVIDER_NOT_FOUND = "RAPI_PROVIDER_NOT_FOUND"

#: All providers in the fallback chain were exhausted without returning data.
RAPI_ALL_PROVIDERS_FAILED = "RAPI_ALL_PROVIDERS_FAILED"

#: A required API key or configuration value is missing from the environment.
RAPI_CONFIG_MISSING = "RAPI_CONFIG_MISSING"

#: The requested data method is not supported by the provider.
RAPI_UNSUPPORTED_METHOD = "RAPI_UNSUPPORTED_METHOD"

# ---------------------------------------------------------------------------
# Description registry
# ---------------------------------------------------------------------------

#: Maps each resource API error code to a human-readable description.
RESOURCE_API_ERRORS: dict[str, str] = {
    RAPI_PROVIDER_NOT_FOUND: (
        "The data provider returned no results for the requested symbol or query. "
        "The symbol may be delisted or the provider's data set does not cover it."
    ),
    RAPI_ALL_PROVIDERS_FAILED: (
        "All data providers in the fallback chain failed. "
        "Check API key configuration and provider availability."
    ),
    RAPI_CONFIG_MISSING: (
        "A required API key or configuration value is missing. "
        "Check the .env file and ensure all required provider keys are set."
    ),
    RAPI_UNSUPPORTED_METHOD: (
        "The requested data method is not supported by this provider. "
        "Verify the method name against the provider's documented interface."
    ),
}
