"""Data pipelines — SQL table-to-table transforms and API ingestion.

Pipeline flow mirrors the SQL schema dependency chain:
  1. ingest_*       — API → fin_markets base tables
  2. compute_*      — base tables → *_exts / *_aggregs / *_stats
  3. build_*        — populate bridge tables and evaluation contexts
  4. calibrate_*    — derive sentiment calibration scales
"""
