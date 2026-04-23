import { BASE, SSE_ORIGIN } from "./config";

// ── SSE Streaming ────────────────────────────────────────────────────────────

/** Health snapshot for an active streaming session (GET /stream/{thread_id}/status). */
export interface StreamingStatusData {
  thread_id: string;
  /** Current user_queries.status value, e.g. "running", "completed". */
  query_status: string;
  /** Tasks whose DB status is still "running". */
  running_tasks: Array<{ task_id: number; task_key: string; node_name: string }>;
  /**
   * Milliseconds since the most-recent token was published to Redis Streams.
   * null if the stream key no longer exists (e.g. stream was deleted on done).
   */
  last_token_ms_ago: number | null;
  /** True if an asyncio.Task for this thread is alive in the backend registry. */
  is_active: boolean;
}

/**
 * Poll the backend streaming-health endpoint.
 *
 * Call when no SSE token event has been received for ≥ 5 seconds while the
 * session is still in loading state.  Returns diagnostic info about whether
 * the backend task is alive and when it last produced tokens.
 */
export async function fetchStreamingStatus(threadId: string): Promise<StreamingStatusData> {
  const res = await fetch(`${BASE}/stream/${threadId}/status`);
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
  return res.json();
}

/** Open an SSE stream for a thread, invoking callbacks on each event.
 *  Returns a cleanup function that closes the connection. */
export function openStream(
  threadId: string,
  handlers: {
    onStarted?: (data: unknown) => void;
    onToken?: (data: unknown) => void;
    /** perf_token_batch events — carries `count` field; always forwarded for silent metric aggregation. */
    onPerfTokenBatch?: (data: unknown) => void;
    /** perf_ingest_progress — emitted ~every second during the ingest phase with produced/total/tps. */
    onPerfIngestProgress?: (data: unknown) => void;
    onCompleted?: (data: unknown) => void;
    onFailed?: (data: unknown) => void;
    onCancelled?: (data: unknown) => void;
    onDone?: (data: unknown) => void;
    /** perf_concurrent_status — emitted every 3 s during concurrent ingest+read; carries batch_size, digest_tps, ingest_tps, stream_len. */
    onPerfConcurrentStatus?: (data: unknown) => void;
    /** perf_ingest_complete — backend ingest phase finished; carries produced, stop_reason. */
    onPerfIngestComplete?: (data: unknown) => void;
    /** perf_test_stopped — timeout fired; freeze all sessions and show final stats. */
    onPerfTestStopped?: (data: unknown) => void;
    /** perf_test_complete — all requested tokens were streamed for this session. */
    onPerfTestComplete?: (data: unknown) => void;
    /**
     * query_status — backend phase transition event.
     * Fired at each processing phase: "received" | "preparing" | "ingesting" | "digesting".
     * Also replayed by the stream endpoint for late-connecting clients via Redis phase store.
     */
    onQueryStatus?: (data: unknown) => void;
    /**
     * query_received — backend accepted the query and persisted it with status='received'.
     * Client must call POST /users/query/{thread_id}/ack to start graph execution.
     * Retried by the pending-notify drain cycle until the ACK is confirmed.
     */
    onQueryReceived?: (data: unknown) => void;
    /**
     * query_ack_confirmed — backend received the client ACK and started LangGraph.
     * Client should stop sending further ACK retries on receipt.
     */
    onQueryAckConfirmed?: (data: unknown) => void;
    onClose?: () => void;
  }
): () => void {
  const sseUrl = `${SSE_ORIGIN}/api/v1/stream/${threadId}`;
  const es = new EventSource(sseUrl);
  console.debug("[stream] EventSource opened url=%s", sseUrl);
  // Prevent onClose from firing more than once (e.g. error then explicit close).
  let closed = false;
  const notifyClose = () => {
    if (closed) return;
    closed = true;
    handlers.onClose?.();
  };

  // Detect persistent CONNECTING failures (e.g. TLS cert not accepted).
  // The browser auto-retries an EventSource in CONNECTING state after each
  // onerror, but if the underlying cause is a rejected TLS certificate the
  // connection will never succeed and the UI stays stuck at "connecting".
  // After _TLS_ERROR_THRESHOLD consecutive errors while still CONNECTING
  // we surface an actionable error via onFailed and stop the EventSource.
  const _TLS_ERROR_THRESHOLD = 3;
  let _connectingErrorCount = 0;
  let _firstEventReceived = false;
  const _markFirstEvent = () => { _firstEventReceived = true; _connectingErrorCount = 0; };

  const parse = (raw: string): unknown => {
    try { return JSON.parse(raw); } catch { return {}; }
  };

  // Mark connection as established on first successful open so the TLS error
  // detector does not trigger on legitimate transient reconnects mid-stream.
  es.onopen = () => { _markFirstEvent(); };

  es.addEventListener("started", (e: MessageEvent) => {
    _markFirstEvent();
    console.debug("[stream] ⇒ started threadId=%s data=%s", threadId, e.data);
    handlers.onStarted?.(parse(e.data));
  });
  // Track first-token timing for debugging.
  let _firstToken = true;
  es.addEventListener("token", (e: MessageEvent) => {
    if (_firstToken) {
      _firstToken = false;
      console.debug("[stream] ⇒ first_token threadId=%s data=%s", threadId, e.data.slice(0, 80));
    }
    handlers.onToken?.(parse(e.data));
  });
  es.addEventListener("perf_token_batch", (e: MessageEvent) => {
    handlers.onPerfTokenBatch?.(parse(e.data));
  });
  es.addEventListener("perf_ingest_progress", (e: MessageEvent) => {
    handlers.onPerfIngestProgress?.(parse(e.data));
  });
  es.addEventListener("perf_ingest_complete", (e: MessageEvent) => {
    handlers.onPerfIngestComplete?.(parse(e.data));
  });
  es.addEventListener("perf_concurrent_status", (e: MessageEvent) => {
    handlers.onPerfConcurrentStatus?.(parse(e.data));
  });
  es.addEventListener("completed", (e: MessageEvent) => {
    console.debug("[stream] ⇒ completed threadId=%s", threadId);
    handlers.onCompleted?.(parse(e.data));
  });
  es.addEventListener("failed", (e: MessageEvent) => {
    console.debug("[stream] ⇒ failed threadId=%s data=%s", threadId, e.data);
    handlers.onFailed?.(parse(e.data));
  });
  es.addEventListener("cancelled", (e: MessageEvent) => {
    console.debug("[stream] ⇒ cancelled threadId=%s", threadId);
    handlers.onCancelled?.(parse(e.data));
  });
  es.addEventListener("done", (e: MessageEvent) => {
    console.debug("[stream] ⇒ done threadId=%s data=%s", threadId, e.data);
    handlers.onDone?.(parse(e.data));
  });
  es.addEventListener("perf_test_stopped", (e: MessageEvent) => {
    console.debug("[stream] ⇒ perf_test_stopped threadId=%s data=%s", threadId, e.data);
    handlers.onPerfTestStopped?.(parse(e.data));
  });
  es.addEventListener("perf_test_complete", (e: MessageEvent) => {
    console.debug("[stream] ⇒ perf_test_complete threadId=%s data=%s", threadId, e.data);
    handlers.onPerfTestComplete?.(parse(e.data));
  });

  es.addEventListener("query_status", (e: MessageEvent) => {
    console.debug("[stream] ⇒ query_status threadId=%s data=%s", threadId, e.data);
    handlers.onQueryStatus?.(parse(e.data));
  });
  es.addEventListener("query_received", (e: MessageEvent) => {
    console.debug("[stream] ⇒ query_received threadId=%s", threadId);
    handlers.onQueryReceived?.(parse(e.data));
  });
  es.addEventListener("query_ack_confirmed", (e: MessageEvent) => {
    console.debug("[stream] ⇒ query_ack_confirmed threadId=%s", threadId);
    handlers.onQueryAckConfirmed?.(parse(e.data));
  });
  // EventSource.CLOSED = 2; only treat a persistent error as a real drop.
  // Transient errors (CONNECTING = 0) are browser-managed retries.
  // However, if the connection never opens (e.g. TLS cert not accepted),
  // errors keep firing in CONNECTING state — detect this and surface a
  // clear error so the user knows to accept the certificate.
  es.onerror = () => {
    if (es.readyState === EventSource.CLOSED) {
      notifyClose();
      return;
    }
    // readyState === CONNECTING — browser is auto-retrying.
    if (!_firstEventReceived) {
      _connectingErrorCount++;
      if (_connectingErrorCount >= _TLS_ERROR_THRESHOLD) {
        const sseHost = new URL(sseUrl).host;
        console.error(
          "[stream] SSE connection failed after %d retries threadId=%s url=%s — " +
          "likely TLS certificate not accepted. Visit %s in this browser and accept the cert.",
          _connectingErrorCount, threadId, sseUrl, SSE_ORIGIN,
        );
        closed = true;
        es.close();
        handlers.onFailed?.({
          message:
            `SSE connection refused (TLS certificate not accepted for ${sseHost}). ` +
            `Open ${SSE_ORIGIN} in this browser tab and click "Accept" / "Proceed anyway", then retry.`,
          error: "tls_cert_not_accepted",
        });
      }
    }
  };

  // Intentional close (component cleanup / explicit teardown): set `closed`
  // directly so any subsequent onerror cannot fire onClose, but do NOT invoke
  // notifyClose() — callers that need to react to close (e.g. closeSession)
  // have already handled their own status patching.
  return () => {
    closed = true;
    es.close();
  };
}

/** Register the task the client currently has expanded in the TaskDrawer.
 *  Passing null unwatches (panel collapsed / drawer closed).
 *  The SSE stream will then suppress token events for tasks not being watched. */
export async function watchTask(threadId: string, taskId: number | null): Promise<void> {
  console.debug("[stream] watchTask threadId=%s taskId=%s", threadId, taskId);
  await fetch(`${BASE}/stream/${encodeURIComponent(threadId)}/watch`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ task_id: taskId }),
  });
  console.debug("[stream] watchTask PUT done threadId=%s taskId=%s", threadId, taskId);
}
