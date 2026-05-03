"""Resources error code registry package.

Re-exports all error code constants and the ``RESOURCE_API_ERRORS`` description dict::

    from backend.resources.errors import (
        RESOURCE_API_ERRORS,
        RAPI_PROVIDER_NOT_FOUND,
        RAPI_ALL_PROVIDERS_FAILED,
        RAPI_CONFIG_MISSING,
        RAPI_UNSUPPORTED_METHOD,
    )
"""

from __future__ import annotations

from backend.resources.errors.codes import (
    RESOURCE_API_ERRORS,
    RAPI_PROVIDER_NOT_FOUND,
    RAPI_ALL_PROVIDERS_FAILED,
    RAPI_CONFIG_MISSING,
    RAPI_UNSUPPORTED_METHOD,
)

__all__ = [
    "RESOURCE_API_ERRORS",
    "RAPI_PROVIDER_NOT_FOUND",
    "RAPI_ALL_PROVIDERS_FAILED",
    "RAPI_CONFIG_MISSING",
    "RAPI_UNSUPPORTED_METHOD",
]
