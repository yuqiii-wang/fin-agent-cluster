"""centrifugo.errors — structured error codes for the Centrifugo integration layer."""

from backend.centrifugo.errors.codes import (
    CENTRIFUGO_PUBLISH_FAILED,
    CENTRIFUGO_NO_NODES,
)

__all__ = [
    "CENTRIFUGO_PUBLISH_FAILED",
    "CENTRIFUGO_NO_NODES",
]
