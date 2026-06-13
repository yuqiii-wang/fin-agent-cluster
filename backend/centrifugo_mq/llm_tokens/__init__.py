"""centrifugo_mq.llm_tokens -- LLM token streaming pipeline.

Architecture
------------
centrifugo-llm-{n} nodes consume LLM tokens directly from Redis Streams
(``fin:llm:tokens:{shard}``).  FastAPI writes each token via XADD so that
Centrifugo picks it up and pushes it to connected WebSocket subscribers.

In-process queues (``asyncio.Queue``) give the LangGraph stream callback a
non-blocking path; a lock per thread serialises concurrent flushes.

Usage::

    from backend.centrifugo_mq.llm_tokens import push_token, end_stream

    # inside an LLM streaming callback:
    await push_token(thread_id, node_id, token_text)

    # when the stream finishes:
    await end_stream(thread_id, node_id)

Implementation split
--------------------
stream.py -- push_token and end_stream public API, queue/lock management
"""

from backend.centrifugo_mq.llm_tokens.stream import end_stream, push_token

__all__ = ["push_token", "end_stream"]
