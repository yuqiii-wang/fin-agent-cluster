"""perf_test agent — LangGraph node for streaming performance tests.

Sub-modules
-----------
node           — ``perf_test_streamer`` LangGraph node function
models         — ``PerfTestOutput`` Pydantic output model
tasks          — ingest driver (``run_ingest``) and pub reader (``perf_stream_reader_gen``)
celery_ingest  — dedicated PerfIngest Celery app for bulk token production
"""

from backend.graph.agents.perf_test.node import perf_test_streamer

__all__ = ["perf_test_streamer"]

