import { useCallback, useEffect, useRef, useState } from "react";
import { openStream } from "../../api";
import { ackQuery } from "../../api/queries";
import { DoneConditionGuard, sendDoneAck } from "./lifecycle";
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
 * Lifecycle phases:
 *   connecting → streaming → draining → done
 *
 * `draining` phase: triggered when the backend emits `done`.
 *   A DoneConditionGuard checks that every task that was started has reached
 *   a terminal state (completed / failed / cancelled) before the done-ACK is
 *   sent and the session transitions to `done`.  This guards against the race
 *   where the lifecycle channel delivers `done` slightly ahead of the last
 *   `completed` task events.  A 2-second drain window acts as a safety net.
 *
 * Additional behaviours:
 *   - On `query_received` → sends ACK; retried until `query_ack_confirmed`.
 *   - On `query_ack_confirmed` → stops ACK retries; graph is running.
 *   - `isTaskOpen = false` → starts `disconnected`; caller renders "Resume".
 *   - On unexpected connection drop → status becomes `disconnected`.
 *
 * @param threadId   Thread to subscribe to. Pass `null` to stay idle.
 * @param isTaskOpen Whether the remote task is currently active. Controls auto-connect.
 * @param token      User bearer token required for ACK and done-ACK endpoints.
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
  // Synchronous mirror of `tasks` state for condition checks inside guard closures.
  const tasksRef = useRef<FinTaskSnapshot[]>([]);
  // Active DoneConditionGuard — created in onDone, cleaned up on unmount.
  const guardRef = useRef<DoneConditionGuard | null>(null);

  /** Internal: open the SSE stream for `tid`, wire all event handlers. */
  const _connect = useCallback((tid: string) => {
    cleanupRef.current?.();
    guardRef.current?.cleanup();
    guardRef.current = null;
    setStatus("connecting");
    setTasks([]);
    tasksRef.current = [];
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
          const updated = [
            ...prev,
            {
              task_id: d.task_id,
              node_name: d.node_name,
              task_key: d.task_key,
              status: "running" as const,
              output: {},
            },
          ];
          tasksRef.current = updated;
          return updated;
        });
      },

      onCompleted: (data) => {
        const d = data as {
          task_id: number;
          output?: Record<string, unknown>;
        };
        setTasks((prev) => {
          const updated = prev.map((t) =>
            t.task_id === d.task_id
              ? { ...t, status: "completed" as const, output: d.output ?? {} }
              : t,
          );
          tasksRef.current = updated;
          return updated;
        });
        // A completed task may satisfy the done-guard condition.
        guardRef.current?.recheck();
      },

      onFailed: (data) => {
        const d = data as {
          task_id: number;
          output?: Record<string, unknown>;
        };
        setTasks((prev) => {
          const updated = prev.map((t) =>
            t.task_id === d.task_id
              ? { ...t, status: "failed" as const, output: d.output ?? {} }
              : t,
          );
          tasksRef.current = updated;
          return updated;
        });
        guardRef.current?.recheck();
      },

      onCancelled: (data) => {
        const d = data as { task_id: number };
        setTasks((prev) => {
          const updated = prev.map((t) =>
            t.task_id === d.task_id
              ? { ...t, status: "cancelled" as const }
              : t,
          );
          tasksRef.current = updated;
          return updated;
        });
        guardRef.current?.recheck();
      },

      onDone: (data) => {
        const d = data as { status?: string };
        const doneStatus = d.status ?? "completed";

        // Guard against duplicate done events (drain-cycle redelivery).
        if (terminated) return;
        terminated = true;

        // Transition to draining phase — backend has signalled session end.
        setStatus("draining");

        const commit = (forced: boolean) => {
          console.info(
            "[useFinStreamSession] done-handshake resolved forced=%s doneStatus=%s thread_id=%s",
            forced, doneStatus, tid,
          );
          sendDoneAck(tid, token, doneStatus).catch((err) => {
            console.warn("[useFinStreamSession] done-ack failed thread_id=%s", tid, err);
          });
          guardRef.current = null;
          setStatus("done");
          // Close SSE — task is complete; caller renders a "Resume" button if desired.
          cleanupRef.current?.();
          cleanupRef.current = null;
        };

        // For successful completions: wait for all started tasks to reach a
        // terminal state before committing.  This guards against the race where
        // `done` arrives via the lifecycle channel before the last `completed`
        // task event from the same channel.
        //
        // For failed / cancelled sessions: tasks may remain "running" because the
        // graph was aborted.  Commit immediately — waiting would never resolve.
        if (doneStatus === "completed") {
          const guard = new DoneConditionGuard({
            label: `fin:${tid}`,
            drainWindowMs: 2_000,
            conditions: [
              () => tasksRef.current.every((t) => t.status !== "running"),
            ],
            onReady: commit,
          });
          guardRef.current = guard;
          guard.trigger();
        } else {
          commit(false);
        }
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
      tasksRef.current = [];
    }
    return () => {
      guardRef.current?.cleanup();
      guardRef.current = null;
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
    guardRef.current?.cleanup();
    guardRef.current = null;
    cleanupRef.current?.();
    cleanupRef.current = null;
    setStatus("disconnected");
  }, []);

  return { status, tasks, reconnect, disconnect };
}
