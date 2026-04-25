/**
 * streaming/lifecycle — done-handshake protocol for streaming sessions.
 *
 * Provides the DoneConditionGuard class and sendDoneAck function used by
 * useFinStreamSession and usePerfSession to implement the draining phase
 * between receiving the backend `done` signal and marking the UI complete.
 *
 * Typical usage pattern:
 *
 *   onDone: (data) => {
 *     setStatus("draining");
 *     const guard = new DoneConditionGuard({
 *       label: `fin:${threadId}`,
 *       conditions: [() => allTasksTerminal()],
 *       onReady: (forced) => {
 *         sendDoneAck(threadId, token, doneStatus).catch(() => {});
 *         setStatus("done");
 *         closeSSE();
 *       },
 *     });
 *     guard.trigger();
 *   },
 *
 *   onCompleted: (data) => {
 *     updateTasks(data);
 *     guard.recheck();  // may resolve if all tasks are now terminal
 *   },
 */

export { DoneConditionGuard } from "./doneGuard";
export { sendDoneAck } from "./ack";
export type {
  StreamLifecyclePhase,
  DoneConditionFn,
  DoneGuardOptions,
} from "./types";
export type { DoneAckPayload, DoneAckResponse } from "./ack";
