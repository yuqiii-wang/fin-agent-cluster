import { useCallback } from "react";
import type React from "react";
import { cancelQuery, createAckHandlers, openStream } from "../../api";
import type { PerfTestConfig, ThreadSession } from "../../components/StreamingPerfTestPanel/types";

export interface PerfSessionDeps {
  cleanups: React.MutableRefObject<Map<string, () => void>>;
  timeouts: React.MutableRefObject<Map<string, ReturnType<typeof setTimeout>>>;
  config: PerfTestConfig;
  patch: (thread_id: string, delta: Partial<ThreadSession>) => void;
  setSessions: React.Dispatch<React.SetStateAction<ThreadSession[]>>;
  closeSession: (thread_id: string, finalStatus?: ThreadSession["status"]) => void;
  freezeAllRef: React.MutableRefObject<() => void>;
  totalTokensRef: React.MutableRefObject<number>;
  /** Guest user token required to send the query ACK. */
  userToken: string;
}

export interface UsePerfSessionReturn {
  /** Open the SSE stream for a single session. */
  openSessionStream: (thread_id: string) => void;
}

/**
 * Unified SSE stream lifecycle hook for perf-test sessions.
 *
 * Manages the browser pub mode: per-token events (`perf_token_batch`),
 * two-phase ingest/pub lifecycle, ACK handshake, phase transitions,
 * and safety timeout.
 *
 * Explicit dequeue: every terminal event handler (`done`, `failed`,
 * `perf_test_stopped`, `perf_test_complete`) calls `dequeue()` — which closes
 * the EventSource immediately via the local cleanup ref — before delegating
 * state updates to `closeSession`.  This releases the HTTP/2 stream slot at
 * the earliest possible moment and removes the session from the shared cleanup
 * registry so that `freezeAll` and a later `closeSession` call are both
 * idempotent and do not double-invoke `es.close()`.
 */
export function usePerfSession(deps: PerfSessionDeps): UsePerfSessionReturn {
  const {
    cleanups,
    timeouts,
    config,
    patch,
    setSessions,
    closeSession,
    freezeAllRef,
    totalTokensRef,
    userToken,
  } = deps;

  const openSessionStream = useCallback(
    (thread_id: string) => {
      let sessionClosed = false;
      let lastIngestLogPct = -1;
      // Running total of tokens received for this session — incremented
      // synchronously in onPerfTokenBatch so we can compare against the
      // target without relying on the async setSessions state.
      let tokensReceived = 0;

      /**
       * Explicit dequeue: close the EventSource immediately and remove this
       * session from the shared cleanup registry and timeout map.
       * Called by every terminal event handler so:
       *  - the HTTP/2 stream slot is released without waiting for GC;
       *  - `freezeAll` and any following `closeSession` are no-ops for this session.
       */
      let esCleanup: (() => void) | null = null;
      const dequeue = () => {
        esCleanup?.();
        esCleanup = null;
        cleanups.current.delete(thread_id);
        const tid = timeouts.current.get(thread_id);
        if (tid !== undefined) {
          clearTimeout(tid);
          timeouts.current.delete(thread_id);
        }
      };

      console.info("[perf] opening stream thread_id=%s", thread_id);

      const cleanup = openStream(thread_id, {
        // ── ACK handshake ────────────────────────────────────────────────────
        ...createAckHandlers(thread_id, userToken, "perf"),

        // ── Phase-transition status ──────────────────────────────────────────
        onQueryStatus: (data) => {
          const d = data as { phase?: string };
          const phaseToStatus: Record<string, ThreadSession["status"]> = {
            received:  "received",
            preparing: "preparing",
            ingesting: "ingesting",
            digesting: "digesting",
          };
          const newStatus = phaseToStatus[d.phase ?? ""];
          if (newStatus) {
            console.info("[perf] %s → %s", thread_id, newStatus);
            // Guard: do not override a terminal status on an already-closed session.
            setSessions((prev) =>
              prev.map((s) => {
                if (s.thread_id !== thread_id || s.closed) return s;
                return { ...s, status: newStatus };
              })
            );
          }
        },

        // ── Shared ingest-phase events ────────────────────────────────────────
        onPerfIngestProgress: (data) => {
          const d = data as { produced?: number; total_tokens?: number; ingest_tps?: number; status?: string };
          if (d.total_tokens) {
            const pct = Math.floor((d.produced ?? 0) / d.total_tokens * 100);
            const milestone = pct - (pct % 25);
            if (milestone > lastIngestLogPct) {
              lastIngestLogPct = milestone;
              console.info(
                "[perf] ingest %s %d%% (%d/%d) tps=%d",
                thread_id, milestone, d.produced ?? 0, d.total_tokens,
                Math.round(d.ingest_tps ?? 0),
              );
            }
          }
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
          const d = data as { produced?: number; stop_reason?: string };
          const status = d.stop_reason === "timeout" ? "timeout" as const : "completed" as const;
          console.info(
            "[perf] ingest complete %s produced=%d stop_reason=%s",
            thread_id, d.produced ?? 0, d.stop_reason ?? "ok",
          );
          patch(thread_id, {
            ingest_produced: d.produced,
            ingest_status: status,
            pub_start_ms: Date.now(),
          });
        },

        // ── Task lifecycle ─────────────────────────────────────────────────────
        onStarted: () => {
          // No-op: perf_token_batch events are always forwarded regardless of
          // watch state, so token counting works without watch-registry wiring.
        },

        onCompleted: (data) => {
          const d = data as { task_key?: string; output?: Record<string, unknown> };
          const key = d?.task_key ?? "";
          console.info("[perf] task completed %s key=%s", thread_id, key);

          if (key === "perf_test_streamer.mock_ingest") {
            // Phase-1 ingest task completed; second half still running concurrently.
            // onPerfIngestHalfComplete handles the visual state; set pub_start_ms as fallback.
            patch(thread_id, { pub_start_ms: Date.now() });
            return;
          }

          if (key === "perf_test_streamer.mock_pub") {
            patch(thread_id, { pub_status: "completed" });
            return;
          }
        },

        // ── Browser-only events ────────────────────────────────────────────────
        onPerfTokenBatch: (data) => {
          const d = data as { count?: number };
          const count = d.count ?? 1;
          tokensReceived += count;
          const now = Date.now();
          setSessions((prev) =>
            prev.map((s) => {
              if (s.thread_id !== thread_id) return s;
              // Ensure status reflects active streaming even if the query_status
              // "digesting" event was missed (e.g. late SSE connect race).
              const activeStatus =
                s.status === "connecting" || s.status === "received" ||
                s.status === "preparing" || s.status === "ingesting"
                  ? "digesting" as const
                  : s.status;
              return {
                ...s,
                status: activeStatus,
                tokens: s.tokens + count,
                last_token_ms: now,
                // Record the exact wall-clock ms of the first token batch as the
                // authoritative digest start for accurate TPS measurement.
                digest_start_ms: s.digest_start_ms ?? now,
              };
            })
          );
          // Auto-complete in throughput mode: all tokens received — close session immediately.
          // Concurrency mode sessions end via perf_test_stopped (timeout) instead.
          if (tokensReceived >= config.tokenCount && config.testMode === "throughput" && !sessionClosed) {
            console.info(
              "[perf] all tokens received %s count=%d — auto-closing",
              thread_id, tokensReceived,
            );
            sessionClosed = true;
            dequeue();
            closeSession(thread_id, "completed");
          }
        },

        onPerfConcurrentStatus: (data) => {
          // Adaptive reader metrics emitted every 3 s during concurrent Phase-2.
          const d = data as {
            batch_size?: number;
            digest_tps?: number;
            ingest_tps?: number;
            stream_len?: number;
          };
          patch(thread_id, {
            concurrent_batch_size: d.batch_size,
            concurrent_digest_tps: d.digest_tps,
            concurrent_ingest_tps: d.ingest_tps,
            concurrent_stream_len: d.stream_len,
          });
        },

        // ── Terminal lifecycle events ──────────────────────────────────────────
        onPerfTestStopped: (_data) => {
          // This stream timed out on the backend — close it as "timeout".
          // Do NOT freeze other sessions: each stream runs independently and
          // a timeout on one should not tear down still-running peers.
          console.info(
            "[perf] perf_test_stopped %s total=%d",
            thread_id, totalTokensRef.current,
          );
          if (!sessionClosed) {
            sessionClosed = true;
            dequeue();
            closeSession(thread_id, "timeout");
          }
        },

        onPerfTestComplete: (_data) => {
          console.info("[perf] perf test complete %s", thread_id);
          if (!sessionClosed) {
            sessionClosed = true;
            dequeue();
            closeSession(thread_id, "completed");
          }
        },

        onDone: (data) => {
          const { status } = data as { status: string };
          console.info("[perf] done %s status=%s sessionClosed=%s", thread_id, status, sessionClosed);
          // Guard: if a more specific terminal event (perf_test_complete, cancelled,
          // perf_test_stopped) already closed this session, skip.
          // This prevents onDone from overriding a user-cancel with a stale status.
          if (sessionClosed) {
            dequeue();
            return;
          }
          sessionClosed = true;
          dequeue(); // explicit close before state update
          closeSession(
            thread_id,
            (["completed", "cancelled", "failed", "timeout"].includes(status)
              ? status
              : "completed") as ThreadSession["status"],
          );
        },

        onFailed: (data) => {
          const errMsg =
            (data as { message?: string; error?: string })?.message ??
            (data as { message?: string; error?: string })?.error ??
            "Stream failed";
          console.warn("[perf] failed %s error=%s", thread_id, errMsg);
          if (!sessionClosed) {
            sessionClosed = true;
            dequeue(); // explicit close before state update
            patch(thread_id, { error: errMsg });
            closeSession(thread_id, "failed");
          }
        },

        onCancelled: () => {
          // Backend confirmed the cancel — close the session immediately as "cancelled".
          // This is the authoritative terminal event for user-initiated cancels, so we
          // set sessionClosed here to prevent onDone from overriding the status.
          console.info("[perf] cancelled confirmed %s", thread_id);
          if (!sessionClosed) {
            sessionClosed = true;
            dequeue();
            closeSession(thread_id, "cancelled");
          }
        },

        onClose: () => {
          if (!sessionClosed) {
            console.warn("[perf] connection closed unexpectedly %s", thread_id);
            patch(thread_id, { status: "failed", error: "Connection closed unexpectedly", closed: true });
          }
        },
      });

      // Register cleanup for freezeAll and the last-resort safety timeout.
      // dequeue() removes both when a terminal event fires.
      esCleanup = cleanup;
      cleanups.current.set(thread_id, cleanup);
      const sessionTimeoutMs = config.timeoutSecs * 1000;
      const tid = setTimeout(() => {
        // Notify backend with reason="timeout" so it emits done(status="timeout").
        // Do NOT call closeSession here — onDone drives the final status update
        // via the backend pg_notify path, keeping all status transitions backend-authoritative.
        cancelQuery(thread_id, "timeout").catch(() => {});
      }, sessionTimeoutMs);
      timeouts.current.set(thread_id, tid);
    },
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [patch, setSessions, closeSession, cleanups, timeouts, config.timeoutSecs, config.tokenCount, config.testMode, freezeAllRef, totalTokensRef, userToken],
  );

  return { openSessionStream };
}
