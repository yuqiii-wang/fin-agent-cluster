# Debug: MOCK_ANALYSIS_PREVIEW Token Loss & End-Signal Architecture

## Symptom

In single-test mode, `MOCK_ANALYSIS_PREVIEW` shows **"Streaming…706 tokens"** in the
inspector panel for 1–2 seconds at the end of the 15 s run, then resolves.  
The backend consistently produces **760 tokens** (`produced=760 elapsed_ms≈15210`).

---

## Investigation

### Backend behaviour (confirmed via logs)

| Log | Evidence |
|---|---|
| `backend/logs/graph.log` | `produced=760 elapsed_ms=15211-15229` on every run — loop always completes |
| `backend/logs/sse_notifications.log` | `[task] publish event=completed` always present |
| `backend/logs/centrifugo.log` | One-off centrifugo-sse outage at 2026-05-07 11:04 for thread `4847a401`; recent runs clean |

The backend is **correct**: all 760 tokens are published to `fin:llm:tokens` via XADD and
`complete_task()` successfully publishes the `completed` lifecycle event.

---

## Root Causes

### Issue 1 — `enableTaskStream` startup race (deterministic, ~20 tokens lost)

**Flow:**
```
Backend : create_task → publish `started` → centrifugo-sse HTTP POST
Frontend: onStarted fires → enableTaskStream(thread_id, taskId) [async, no await]
Backend : token loop starts IMMEDIATELY after create_task returns
Backend : batch 1 → store_preview_token × 20 → is_task_stream_live? → Redis GET
                                                                         ↑ live key NOT SET YET
→ batch 1 tokens are buffered in Redis but NOT published to centrifugo-llm
```

**Timing:** centrifugo-sse WebSocket delivery (50–200 ms) + nginx HTTP round-trip for
`enableTaskStream` (20–50 ms) = **70–250 ms** before the live key is set.  
At `_BATCH_SIZE=20, _TOKEN_PER_SEC=50` → batch period = 0.4 s.  
Any batch whose `is_task_stream_live` check executes before the live key arrives is silently
skipped. Typically 1 batch (20 tokens) is lost; under load 2–3 batches.

The buffered tokens in `preview_tokens:{thread_id}:{task_id}` (Redis List) are **never
replayed** to the live stream — `enable_task_stream()` currently only does a `SETEX`.

**Fix:** Extend `enable_task_stream()` to `LRANGE` the buffer and publish each token
back via `stream_token()` before (or atomically with) setting the live flag.

### Issue 2 — `openTokenStream` has `recoverable: false` (intermittent, 0–50 tokens lost)

`openTokenStream` in `stream.ts` defaults `recoverable = options.recoverHistory === true`
which evaluates to **false** unless explicitly passed.  `useSingleTestSession.ts` does not
pass `recoverHistory: true`.  
centrifugo-llm is configured with `recoverable: false` by design (high-throughput perf
stream), so a brief WebSocket blip during the 15 s run loses those tokens permanently.

At 50 tokens/s a 1 s drop ≈ 50 tokens lost, consistent with the observed shortfall.

**Fix:** For opt-in preview streams this is acceptable (tokens are buffered in Redis).
The replay fix for Issue 1 also covers the startup window. True mid-stream WebSocket
drops are best handled by telling users they can re-enable streaming to get the buffered
tokens.

### Issue 3 — "Stuck for a long time" = end-of-task gap (~1–2 s)

At the end of the 15 s loop:
1. Loop exits → `complete_task()` call
2. HTTP POST to `centrifugo-sse-{shard}` (publish latency 50–350 ms seen in logs)
3. centrifugo-sse delivers `completed` via WebSocket (~10–50 ms)
4. Frontend `task_terminal` dispatch → React re-render

During this **~0.5–1.5 s gap**, no new tokens arrive but `task.status` is still `"running"`.
The display correctly shows "Streaming…N tokens" — it is **not actually stuck**; it is
waiting for the `completed` lifecycle event.

---

## End-Signal Architecture (all LLM paths)

There is **no in-band end-of-stream marker** in `fin:llm:tokens`.  
The authoritative end signal is always `complete_task()` → centrifugo-sse HTTP → `completed`
lifecycle event → frontend `task_terminal` dispatch.

| Path | Token producer | Who calls `complete_task` |
|---|---|---|
| MOCK_ANALYSIS_PREVIEW | FastAPI asyncio loop (no celery) | FastAPI node directly after loop exits |
| MockChatModel (perf) | Celery `fanout`/`throughput` via `llm.astream` | FastAPI node after celery task returns |
| Ollama | Celery `invoke_llm` via `ChatOpenAI.astream`; Ollama sends `finish_reason: stop` → generator exhausts | FastAPI node after `invoke_llm` result |
| ARK / Gemini | Same celery `invoke_llm` via LangChain adapters | Same |

---

## Celery `invoke_llm` Retry Bug (separate issue, real LLM paths only)

`invoke_llm` is defined with `max_retries=3, default_retry_delay=5`.  
On retry it creates a **fresh LLM instance** and calls `llm.astream(messages)` from scratch,
publishing new tokens to the **same `fin:llm:tokens`** shard.

The frontend accumulates tokens from both attempts → garbled/duplicated stream content.

**Not applicable to `MOCK_ANALYSIS_PREVIEW`** (runs in FastAPI asyncio, no celery).

**Fix:** On retry, do not re-publish to the token stream. Either:
- Skip `_xadd_token` on retry attempts (`self.request.retries > 0`), or  
- Assign a per-attempt unique stream key so retries go to a different channel.

---

## Files Involved

| File | Role |
|---|---|
| `backend/graph/agents/mock_single/nodes/analysis_node/tasks/analysis.py` | MOCK_ANALYSIS_PREVIEW task — token loop, `is_task_stream_live`, `complete_task` |
| `backend/db/redis/session/task_preview.py` | Live flag + token buffer — `enable_task_stream`, `is_task_stream_live`, `store_preview_token` |
| `backend/sse_notifications/task/` | `complete_task`, `fail_task` lifecycle publishers |
| `backend/centrifugo/client.py` | HTTP client for centrifugo-sse; fire-and-forget with 2 retries |
| `backend/streaming/workers/llm_ingest.py` | `invoke_llm` celery task — retry issue |
| `frontend/src/services/singleTest/useSingleTestSession.ts` | `onStarted` → `enableTaskStream` (async, no await) |
| `frontend/src/api/stream.ts` | `openTokenStream` — `recoverable: false` default |
| `frontend/src/components/OutputViewer/renderers/StreamingTaskOutput.tsx` | "Streaming…N tokens" display |
