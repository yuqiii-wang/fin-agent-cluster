/**
 * Streaming service — SSE session hooks for stream runs.
 *
 * usePerfSession — per-thread SSE for browser-mode (per-token events).
 *                  All lifecycle management is shared.
 *
 * Lifecycle utilities (lifecycle/):
 *   DoneConditionGuard — manages the draining phase between `done` signal and ACK.
 *   sendDoneAck        — sends the client done-ACK to POST /stream/{id}/done-ack.
 *   StreamLifecyclePhase — full phase enum including `draining`.
 */

export { usePerfSession } from "./usePerfSession";
export type { UsePerfSessionReturn, PerfSessionDeps } from "./usePerfSession";

export type { FinStreamStatus, FinTaskSnapshot } from "./types";

export { DoneConditionGuard, sendDoneAck } from "./lifecycle";
export type { StreamLifecyclePhase, DoneConditionFn, DoneGuardOptions, DoneAckPayload, DoneAckResponse } from "./lifecycle";
