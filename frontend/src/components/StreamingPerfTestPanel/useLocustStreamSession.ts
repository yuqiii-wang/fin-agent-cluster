import { useCallback } from "react";
import type React from "react";
import { cancelQuery, openStream } from "../../api";
import type { PerfTestConfig, ThreadSession } from "./types";

export interface LocustStreamSessionDeps {
  cleanups: React.MutableRefObject<Map<string, () => void>>;
  timeouts: React.MutableRefObject<Map<string, ReturnType<typeof setTimeout>>>;
  config: PerfTestConfig;
  patch: (thread_id: string, delta: Partial<ThreadSession>) => void;
  setSessions: React.Dispatch<React.SetStateAction<ThreadSession[]>>;
  closeSession: (thread_id: string, finalStatus?: ThreadSession["status"]) => void;
  freezeAllRef: React.MutableRefObject<() => void>;
  totalTokensRef: React.MutableRefObject<number>;
}

export interface UseLocustStreamSessionReturn {
  /** Open the SSE stream for a single locust-mode session. */
  openSessionStream: (thread_id: string) => void;
}

/**
 * Manages the SSE stream lifecycle for a locust-mode perf-test session.
 * Unlike the browser mode, there are no per-token events; the session waits
 * for a `locust_complete` event carrying aggregated digest metrics.
 */
export function useLocustStreamSession(
  deps: LocustStreamSessionDeps,
): UseLocustStreamSessionReturn {
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
   * timeout that self-heals the session if locust_complete never arrives.
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
   * Open the SSE stream for `thread_id` in locust mode.
   * Handles `locust_complete`, `perf_test_stopped`, terminal lifecycle events,
   * and the `perf_ingest_complete` handoff — but intentionally omits
   * per-token (`perf_token`) and ingest-progress events.
   */
  const openSessionStream = useCallback(
    (thread_id: string) => {
      // Status is driven by backend query_status events; stay "connecting" until received.
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
                pub_start_ms: s.pub_start_ms ?? (isIngestDone ? Date.now() : undefined),
              };
            })
          );
        },
        onPerfIngestComplete: (data) => {
          // Ingest phase finished — transition visual state to "pub" phase.
          const d = data as { ingest_ms?: number; produced?: number; stop_reason?: string };
          const status = d.stop_reason === "timeout" ? "timeout" as const : "completed" as const;
          patch(thread_id, {
            ingest_ms: d.ingest_ms,
            ingest_produced: d.produced,
            ingest_status: status,
            pub_start_ms: Date.now(),
          });
        },
        onLocustComplete: (data) => {
          // Locust digest finished: update token count + tps + digest_ms from digest metrics.
          const d = data as { consumed?: number; tps?: number; digest_ms?: number };
          const consumed = d.consumed ?? 0;
          const tps = d.tps ?? 0;
          const digestMs = d.digest_ms;
          const now = Date.now();
          totalTokensRef.current += consumed;
          setSessions((prev) =>
            prev.map((s) => {
              if (s.thread_id !== thread_id) return s;
              return {
                ...s,
                tokens: consumed,
                last_token_ms: now,
                digest_tps: tps,
                digest_ms: digestMs,
                pub_status: "completed",
              };
            }),
          );
          sessionClosed = true;
          closeSession(thread_id, "completed");
        },
        onPerfTestStopped: (_data) => {
          console.info(
            "[perf_panel:locust] perf_test_stopped: total consumed=%d",
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
          // Keep EventSource open — perf_test_stopped / done will close the session.
        },
        onClose: () => {
          if (!sessionClosed) {
            patch(thread_id, {
              status: "failed",
              error: "Connection closed unexpectedly",
              closed: true,
            });
          }
        },
      });

      attachStream(thread_id, cleanup);
    },
    [patch, setSessions, closeSession, attachStream, freezeAllRef, totalTokensRef],
  );

  return { openSessionStream };
}
