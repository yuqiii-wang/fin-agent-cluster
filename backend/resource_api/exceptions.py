"""Shared exception types for the resource_api layer."""

from __future__ import annotations


class ProviderNotFoundError(Exception):
    """Raised by a provider when the requested symbol / query returns no data.

    Distinguishes a "symbol not found" or "HTTP 404" outcome from transient
    errors (network failure, rate-limit, auth error).  The client uses this
    to try the next provider and, when all providers raise it, to surface a
    structured "not found" result instead of re-raising.

    Attributes:
        provider: Short provider name, e.g. ``"alpha_vantage"``.
        service:  Specific endpoint or API function that was called,
                  e.g. ``"TIME_SERIES_DAILY"`` or ``"yfinance Ticker.history()"``
        symbol:   Symbol or query text that was not found.
        detail:   Original error message or HTTP status for diagnostics.
    """

    def __init__(
        self,
        provider: str,
        service: str,
        symbol: str,
        detail: str = "",
    ) -> None:
        """Initialise with provider metadata.

        Args:
            provider: Short provider identifier.
            service:  Endpoint / API function attempted.
            symbol:   Symbol or query searched.
            detail:   Extra diagnostic info (HTTP status, error body, etc.).
        """
        self.provider = provider
        self.service = service
        self.symbol = symbol
        self.detail = detail
        super().__init__(
            f"{provider} [{service}] → not found for {symbol!r}"
            + (f": {detail}" if detail else "")
        )

    def as_log_entry(self) -> str:
        """Return a human-readable one-line description for log output.

        Returns:
            String like ``"alpha_vantage [TIME_SERIES_DAILY] → XXXX: HTTP 404 Not Found"``
        """
        base = f"{self.provider} [{self.service}]"
        if self.detail:
            return f"{base}: {self.detail}"
        return base
