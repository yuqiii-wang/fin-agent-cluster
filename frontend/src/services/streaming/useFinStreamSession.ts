import { useCallback, useEffect, useRef, useState } from "react";
import { openStream } from "../../api";
import { ackQuery } from "../../api/queries";
import type { FinStreamStatus, FinTaskSnapshot } from "./types";

export interface UseFinStreamSessionReturn {
  /** Current lifecycle state of the stream connection. */
  status: FinStreamStatus;
  /** Accumulated task snapshots populated from SSE events. */
  tasks: FinTaskSnapshot[];
  /**
   * Re-open the SSE connection.
   * Clears existing task snapshots and reconnects from scratch.
   * Callable regardless of current status; intended as the "Resume" action.
   */
  reconnect: () => void;
  /** Explicitly close the SSE connection and set status to 'disconnected'. */
  disconnect: () => void;
}

/**
 * Manages a single SSE stream session for a regular fin query.
 *
 * Behaviour:
 *  - `isTaskOpen = true`  → auto-connects on mount; handles query_received ACK
 *    handshake, then populates `tasks` from SSE events once graph runs.
 *  - `isTaskOpen = false` → starts in `disconnected` state (thread exists but task is already
 *    done); caller should render a "Resume" button that calls `reconnect()`.
 *  - On `query_received` SSE event → sends ACK to backend; retried on each re-delivery
 *    until `query_ack_confirmed` is received.
 *  - On `query_ack_confirmed` → stops ACK retries; graph is now running.
 *  - On terminal `done` event → SSE is closed cleanly, status becomes `done`.
 *  - On unexpected connection drop → status becomes `disconnected`.
 *
 * @param threadId   Thread to subscribe to. Pass `null` to stay idle.
 * @param isTaskOpen Whether the remote task is currently active. Controls auto-connect.
 * @param token      User bearer token required to call the ACK endpoint.
 */
export function useFinStreamSession(
  threadId: string | null,
  isTaskOpen: boolean,
  token: string | null,
): UseFinStreamSessionReturn {
  const [status, setStatus] = useState<FinStreamStatus>(() => {
    if (!threadId) return "idle";
    return isTaskOpen ? "connecting" : "disconnected";
  });
  const [tasks, setTasks] = useState<FinTaskSnapshot[]>([]);
  const cleanupRef = useRef<(() => void) | null>(null);
  // Prevent concurrent in-flight ACK POSTs and stop retrying after confirmation.
  const ackInFlightRef = useRef(false);
  const ackConfirmedRef = useRef(false);

  /** Internal: open the SSE stream for `tid`, wire all event handlers. */
  const _connect = useCallback((tid: string) => {
    cleanupRef.current?.();
    setStatus("connecting");
    setTasks([]);
    ackInFlightRef.current = false;
    ackConfirmedRef.current = false;

    let terminated = false;

    const cleanup = openStream(tid, {
      onQueryReceived: (_data) => {
        // Each delivery (live or drain-cycle retry) triggers an ACK attempt.
        // Guard against concurrent in-flight POSTs; stop once confirmed.
        if (ackConfirmedRef.current || ackInFlightRef.current || !token) return;
        ackInFlightRef.current = true;
        ackQuery(tid, token)
          .catch((err) => {
            console.warn("[useFinStreamSession] ack failed, will retry on next query_received", err);
          })
          .finally(() => {
            ackInFlightRef.current = false;
          });
      },

      onQueryAckConfirmed: (_data) => {
        // Backend has started the graph — stop all further ACK retries.
        ackConfirmedRef.current = true;
        // Status stays 'connecting' until the first 'started' task event.
      },

      onStarted: (data) => {
        const d = data as { task_id: number; node_name: string; task_key: string };
        setStatus("streaming");
        setTasks((prev) => {
          if (prev.some((t) => t.task_id === d.task_id)) return prev;
          return [
            ...prev,
            {
              task_id: d.task_id,
              node_name: d.node_name,
              task_key: d.task_key,
              status: "running",
              output: {},
            },
          ];
        });
      },

      onCompleted: (data) => {
        const d = data as {
          task_id: number;
          output?: Record<string, unknown>;
        };
        setTasks((prev) =>
          prev.map((t) =>
            t.task_id === d.task_id
              ? { ...t, status: "completed", output: d.output ?? {} }
              : t,
          ),
        );
      },

      onFailed: (data) => {
        const d = data as {
          task_id: number;
          output?: Record<string, unknown>;
        };
        setTasks((prev) =>
          prev.map((t) =>
            t.task_id === d.task_id
              ? { ...t, status: "failed", output: d.output ?? {} }
              : t,
          ),
        );
      },

      onCancelled: (data) => {
        const d = data as { task_id: number };
        setTasks((prev) =>
          prev.map((t) =>
            t.task_id === d.task_id ? { ...t, status: "cancelled" } : t,
          ),
        );
      },

      onDone: (_data) => {
        terminated = true;
        setStatus("done");
        // Close SSE — task is complete; caller renders a "Resume" button if desired.
        cleanupRef.current?.();
        cleanupRef.current = null;
      },

      onClose: () => {
        if (!terminated) {
          setStatus("disconnected");
        }
      },
    });

    cleanupRef.current = cleanup;
  }, [token]);

  // Auto-connect lifecycle tied to threadId + isTaskOpen.
  useEffect(() => {
    if (threadId && isTaskOpen) {
      _connect(threadId);
    } else {
      setStatus(threadId ? "disconnected" : "idle");
      setTasks([]);
    }
    return () => {
      cleanupRef.current?.();
      cleanupRef.current = null;
    };
  // _connect is stable (useCallback with [token] dep), safe to include.
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [threadId, isTaskOpen]);

  const reconnect = useCallback(() => {
    if (threadId) _connect(threadId);
  }, [threadId, _connect]);

  const disconnect = useCallback(() => {
    cleanupRef.current?.();
    cleanupRef.current = null;
    setStatus("disconnected");
  }, []);

  return { status, tasks, reconnect, disconnect };
}
