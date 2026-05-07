# Debug: `llm_responses` table always empty

## Symptom

`SELECT COUNT(*) FROM fin_agents.llm_responses` always returned 0 despite
the LLM completing requests.  `fin:llm:completions` Redis stream accumulated
130 entries but none were ever consumed.

## Root cause 1 — Celery beat never started

`run.py` started the `celery-ingest` worker but **not** the beat scheduler.
`persist_llm_completions` is a beat-scheduled task (`beat_interval=10s`).
Without beat, it never fired.

**Fix**: `run.py` `_start_celery()` now launches both the worker and beat as
separate subprocesses.

## Root cause 2 — `raw_conn()` pool unavailable in Celery context

`_upsert_response` used `from backend.db import raw_conn`, which internally
calls `get_raw_pool()`.  That pool is opened by `open_pools()` inside the
FastAPI lifespan.  Celery worker processes are entirely separate; they never
run the FastAPI lifespan, so `_raw_pool` is always `None` and
`get_raw_pool()` raises `RuntimeError([PG_POOL_NOT_OPENED])`.

**Fix**: Replace `raw_conn()` with a dedicated
`psycopg.AsyncConnection.connect()` call scoped to the task function.  This
is the correct pattern for Celery tasks that need DB access: open a short-
lived connection per task execution, don't rely on a shared pool managed by
another process.

## Root cause 3 — Empty-string `task_id` violates FK

Redis Streams store all values as byte strings.  A `None` Python value gets
round-tripped as `""` (empty string) when read back.  The `task_id` column
has a FK constraint to `fin_agents.tasks(task_id)`, so inserting `""` raises:

```
insert or update on table "llm_responses" violates foreign key constraint
"llm_responses_task_id_fkey"
DETAIL: Key (task_id)=() is not present in table "tasks".
```

**Fix**: Added `model_validate` override to `LLMCompletionMessage` in
`backend/streaming/schemas.py` that converts `""` → `None` for all nullable
fields before Pydantic validates them.  This is the right boundary because
the schema is the consumer-side interface for all Redis Stream messages.

## Files changed

| File | Change |
|------|--------|
| `run.py` | `_start_celery()` now starts beat subprocess alongside worker |
| `backend/streaming/workers/pg_persist.py` | `_upsert_response` uses direct `psycopg.AsyncConnection.connect()` instead of `raw_conn()` |
| `backend/streaming/schemas.py` | `LLMCompletionMessage.model_validate` coerces `""` → `None` for nullable fields |
