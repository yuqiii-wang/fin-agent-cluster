"""Error code constants for the Centrifugo integration layer."""

CENTRIFUGO_PUBLISH_FAILED = "CENTRIFUGO_001"
"""HTTP publish to Centrifugo API failed (network error, non-2xx response)."""

CENTRIFUGO_NO_NODES = "CENTRIFUGO_002"
"""CENTRIFUGO_NODES config is empty; at least one node URL is required."""
