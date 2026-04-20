import { BASE, KONG_ORIGIN } from "./config";

// ── SSE Streaming ────────────────────────────────────────────────────────────

/** Open an SSE stream for a thread, invoking callbacks on each event.
 *  Returns a cleanup function that closes the connection. */
export function openStream(
  threadId: string,
  handlers: {
    onStarted?: (data: unknown) => void;
    onToken?: (data: unknown) => void;
    /** perf_token events — always forwarded regardless of watch state; used for silent metric aggregation. */
    onPerfToken?: (data: unknown) => void;
    /** perf_ingest_progress — emitted ~every second during the ingest phase with produced/total/tps. */
    onPerfIngestProgress?: (data: unknown) => void;
    onCompleted?: (data: unknown) => void;
    onFailed?: (data: unknown) => void;
    onCancelled?: (data: unknown) => void;
    onDone?: (data: unknown) => void;
    /** perf_ingest_complete — backend ingest phase finished; carries ingest_ms, produced, stop_reason. */
    onPerfIngestComplete?: (data: unknown) => void;
    /** perf_test_stopped — timeout fired; freeze all sessions and show final stats. */
    onPerfTestStopped?: (data: unknown) => void;
    /** perf_test_complete — all requested tokens were streamed for this session. */
    onPerfTestComplete?: (data: unknown) => void;
    /** locust_complete — locust digest finished; carries consumed, tps, digest_ms. */
    onLocustComplete?: (data: unknown) => void;
    /**
     * query_status — backend phase transition event.
     * Fired at each processing phase: "received" | "preparing" | "ingesting" | "sending".
     * Also replayed by the stream endpoint for late-connecting clients via Redis phase store.
     */
    onQueryStatus?: (data: unknown) => void;
    onClose?: () => void;
  }
): () => void {
  const es = new EventSource(`${KONG_ORIGIN}/api/v1/stream/${threadId}`);
  console.debug("[stream] EventSource opened url=%s", `${KONG_ORIGIN}/api/v1/stream/${threadId}`);
  // Prevent onClose from firing more than once (e.g. error then explicit close).
  let closed = false;
  const notifyClose = () => {
    if (closed) return;
    closed = true;
    handlers.onClose?.();
  };

  const parse = (raw: string): unknown => {
    try { return JSON.parse(raw); } catch { return {}; }
  };

  es.addEventListener("started", (e: MessageEvent) => {
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
  es.addEventListener("perf_token", (e: MessageEvent) => {
    handlers.onPerfToken?.(parse(e.data));
  });
  es.addEventListener("perf_ingest_progress", (e: MessageEvent) => {
    handlers.onPerfIngestProgress?.(parse(e.data));
  });
  es.addEventListener("perf_ingest_complete", (e: MessageEvent) => {
    handlers.onPerfIngestComplete?.(parse(e.data));
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
  es.addEventListener("locust_complete", (e: MessageEvent) => {
    console.debug("[stream] ⇒ locust_complete threadId=%s data=%s", threadId, e.data);
    handlers.onLocustComplete?.(parse(e.data));
  });
  es.addEventListener("query_status", (e: MessageEvent) => {
    console.debug("[stream] ⇒ query_status threadId=%s data=%s", threadId, e.data);
    handlers.onQueryStatus?.(parse(e.data));
  });
  // EventSource.CLOSED = 2; only treat a persistent error as a real drop.
  // Transient errors (CONNECTING = 0) are browser-managed retries — ignore them.
  es.onerror = () => {
    if (es.readyState === EventSource.CLOSED) {
      notifyClose();
    }
    // readyState === CONNECTING means browser is auto-retrying — do nothing.
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
