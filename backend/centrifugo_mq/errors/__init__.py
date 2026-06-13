"""centrifugo.errors -- structured error codes for the Centrifugo integration layer."""

from backend.centrifugo_mq.errors.codes import (
    CENTRIFUGO_PUBLISH_FAILED,
    CENTRIFUGO_NO_NODES,
    CENTRIFUGO_SSE_NACK,
    STREAM_START_NACK,
)

__all__ = [
    "CENTRIFUGO_PUBLISH_FAILED",
    "CENTRIFUGO_NO_NODES",
    "CENTRIFUGO_SSE_NACK",
    "STREAM_START_NACK",
]
