"""Error code constants for the Centrifugo integration layer."""

CENTRIFUGO_PUBLISH_FAILED = "CENTRIFUGO_001"
"""HTTP publish to Centrifugo API failed (network error, non-2xx response)."""

CENTRIFUGO_NO_NODES = "CENTRIFUGO_002"
"""CENTRIFUGO_NODES config is empty; at least one node URL is required."""

CENTRIFUGO_SSE_NACK = "CENTRIFUGO_003"
"""Frontend did not ACK an SSE notification within the timeout window.  A failed event
was automatically published so the frontend always receives a terminal state."""

STREAM_START_NACK = "CENTRIFUGO_004"
"""Frontend did not ACK the stream_start handshake within the timeout window.  The
LLM streaming call proceeds anyway; tokens may be partially missed if the LLM MQ
channel subscription was not established in time."""
