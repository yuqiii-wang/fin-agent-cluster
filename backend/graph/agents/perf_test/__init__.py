"""perf_test agent — LangGraph node for streaming performance tests.

Sub-modules
-----------
node           — ``perf_test_streamer`` LangGraph node function
tasks          — split ingest (``run_ingest_first_half``, ``run_ingest_second_half``),
                 rate-limited ingest (``run_rate_limited_ingest``),
                 adaptive reader (``dynamic_reader_gen``)
celery_ingest  — dedicated PerfIngest Celery app for bulk token production
"""

from backend.graph.agents.perf_test.node import perf_test_streamer

__all__ = ["perf_test_streamer"]

