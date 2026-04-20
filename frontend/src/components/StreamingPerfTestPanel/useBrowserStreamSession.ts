import { useCallback } from "react";
import type React from "react";
import { cancelQuery, openStream } from "../../api";
import type { PerfTestConfig, ThreadSession } from "./types";

export interface BrowserStreamSessionDeps {
  cleanups: React.MutableRefObject<Map<string, () => void>>;
  timeouts: React.MutableRefObject<Map<string, ReturnType<typeof setTimeout>>>;
  config: PerfTestConfig;
  patch: (thread_id: string, delta: Partial<ThreadSession>) => void;
  setSessions: React.Dispatch<React.SetStateAction<ThreadSession[]>>;
  closeSession: (thread_id: string, finalStatus?: ThreadSession["status"]) => void;
  freezeAllRef: React.MutableRefObject<() => void>;
  totalTokensRef: React.MutableRefObject<number>;
}

export interface UseBrowserStreamSessionReturn {
  /** Open the SSE stream for a single session and register its safety timeout. */
  openSessionStream: (thread_id: string) => void;
}

/**
 * Manages the SSE stream lifecycle for a single perf-test session.
 * Owns `attachStream` (cleanup + safety-timeout registration) and
 * `openSessionStream` (event-handler wiring via openStream).
 */
export function useBrowserStreamSession(deps: BrowserStreamSessionDeps): UseBrowserStreamSessionReturn {
  const {
    cleanups,
    timeouts,
    config,
    patch,
    setSessions,
    closeSession,
    freezeAllRef,
    totalTokensRef,
  } = deps;

  /**
   * Register the SSE cleanup function and install a last-resort safety
   * timeout that self-heals the session if neither perf_test_stopped nor
   * done ever arrive (e.g. silent network partition).
   */
  const attachStream = useCallback(
    (thread_id: string, cleanup: () => void) => {
      cleanups.current.set(thread_id, cleanup);
      const sessionTimeoutMs = config.timeoutSecs * 1000;
      const tid = setTimeout(() => {
        cancelQuery(thread_id).catch(() => {});
        closeSession(thread_id, "completed");
      }, sessionTimeoutMs);
      timeouts.current.set(thread_id, tid);
    },
    [cleanups, timeouts, closeSession, config.timeoutSecs],
  );

  /**
   * Open the SSE stream for `thread_id`, wire all perf-test event handlers,
   * and register the stream via `attachStream`.
   */
  const openSessionStream = useCallback(
    (thread_id: string) => {
      // Do NOT immediately set status to "running" — backend query_status events
      // drive status through: received → preparing → ingesting → sending.
      // Status stays "connecting" until the first query_status event arrives.
      let sessionClosed = false;

      const cleanup = openStream(thread_id, {
        onQueryStatus: (data) => {
          const d = data as { phase?: string };
          const phaseToStatus: Record<string, ThreadSession["status"]> = {
            received:  "received",
            preparing: "preparing",
            ingesting: "ingesting",
            sending:   "sending",
          };
          const newStatus = phaseToStatus[d.phase ?? ""];
          if (newStatus) {
            patch(thread_id, { status: newStatus });
          }
        },
        onStarted: (_data) => {
          // No watchTask needed: perf_token events are always forwarded
          // regardless of watch state, so token counting is unaffected by
          // the TaskDrawer open/close lifecycle.
        },
        onPerfToken: (_data) => {
          setSessions((prev) =>
            prev.map((s) => {
              if (s.thread_id !== thread_id) return s;
              // Ensure status reflects active streaming even if the query_status
              // "sending" event was missed (e.g. late SSE connect race).
              const activeStatus =
                s.status === "connecting" || s.status === "received" ||
                s.status === "preparing" || s.status === "ingesting"
                  ? "sending" as const
                  : s.status;
              return { ...s, status: activeStatus, tokens: s.tokens + 1, last_token_ms: Date.now() };
            })
          );
        },
        onPerfIngestProgress: (data) => {
          const d = data as { produced?: number; total_tokens?: number; ingest_tps?: number; status?: string };
          const isIngestDone = d.status === "completed" || d.status === "timeout";
          setSessions((prev) =>
            prev.map((s) => {
              if (s.thread_id !== thread_id) return s;
              return {
                ...s,
                ingest_produced: d.produced,
                ingest_total: d.total_tokens,
                ingest_tps: d.ingest_tps,
                ingest_status: (d.status === "running" || d.status === "completed" || d.status === "timeout")
                  ? d.status
                  : "running",
                // Set pub_start_ms the first time ingest finishes; never overwrite once set.
                pub_start_ms: s.pub_start_ms ?? (isIngestDone ? Date.now() : undefined),
              };
            })
          );
        },
        onPerfIngestComplete: (data) => {
          const d = data as { ingest_ms?: number; produced?: number; stop_reason?: string };
          const status = d.stop_reason === "timeout" ? "timeout" as const : "completed" as const;
          patch(thread_id, {
            ingest_ms: d.ingest_ms,
            ingest_status: status,
            pub_start_ms: Date.now(),
          });
        },
        onCompleted: (data) => {
          // Handle ingest and pub phase completions individually.
          const d = data as { task_key?: string };
          const key = d?.task_key ?? "";
          if (key === "perf_test_streamer.mock_ingest") {
            patch(thread_id, { ingest_status: "completed", pub_start_ms: Date.now() });
          } else if (key === "perf_test_streamer.mock_pub") {
            patch(thread_id, { pub_status: "completed" });
          }
        },
        onPerfTestStopped: (_data) => {
          console.info(
            "[perf_panel] perf_test_stopped: perf_token count at timeout=%d",
            totalTokensRef.current,
          );
          sessionClosed = true;
          freezeAllRef.current();
        },
        onPerfTestComplete: (_data) => {
          sessionClosed = true;
          closeSession(thread_id, "completed");
        },
        onDone: (data) => {
          sessionClosed = true;
          const { status } = data as { status: string };
          closeSession(
            thread_id,
            (["completed", "cancelled", "failed"].includes(status)
              ? status
              : "completed") as ThreadSession["status"],
          );
        },
        onFailed: (data) => {
          sessionClosed = true;
          const errMsg =
            (data as { message?: string; error?: string })?.message ??
            (data as { message?: string; error?: string })?.error ??
            "Stream failed";
          patch(thread_id, { error: errMsg });
          closeSession(thread_id, "failed");
        },
        onCancelled: () => {
          // Task-level cancel (e.g. node CancelledError on timeout) — keep the
          // EventSource open so the following perf_test_stopped / done events
          // can arrive.  Session closure is handled by onDone / onPerfTestStopped.
        },
        onClose: () => {
          if (!sessionClosed) {
            patch(thread_id, { status: "failed", error: "Connection closed unexpectedly", closed: true });
          }
        },
      });

      attachStream(thread_id, cleanup);
    },
    [patch, setSessions, closeSession, attachStream, freezeAllRef, totalTokensRef],
  );

  return { openSessionStream };
}
