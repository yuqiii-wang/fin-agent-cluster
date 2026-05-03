/**
 * Streaming service — SSE session hooks for stream runs.
 *
 * usePerfSession — per-thread SSE for browser-mode (per-token events).
 *
 * Core streaming infrastructure (core/):
 *   lifecycle/          — DoneConditionGuard + done/status ACK senders
 *   errors/             — UI-side streaming error codes
 *   sessionState        — mutable per-session closure state
 *   sessionHelpers      — dequeue / terminate / drainGuard lifecycle helpers
 *   phaseHandlers       — query_status / ingest_complete / started / completed
 *   tokenHandler        — perf_token_batch buffering + auto-complete
 *   terminalHandlers    — done / failed / cancelled / close handlers
 */

export { usePerfSession } from "./usePerfSession";
export type { UsePerfSessionReturn, PerfSessionDeps } from "./usePerfSession";

export type { FinStreamStatus, FinTaskSnapshot } from "./types";

// Re-export core streaming infrastructure for use by any session type.
export {
  DoneConditionGuard,
  sendDoneAck,
  sendStatusAck,
  UI_STREAMING_ERRORS,
  getErrorDescription,
  createSessionClosureState,
  createSessionHelpers,
  createPhaseHandlers,
  createTokenHandler,
  createTerminalHandlers,
} from "./core";
export type {
  StreamLifecyclePhase,
  DoneConditionFn,
  DoneGuardOptions,
  DoneAckPayload,
  DoneAckResponse,
  SessionClosureState,
  SessionHelpers,
  PhaseHandlerDeps,
  TokenHandlerDeps,
  TerminalHandlerDeps,
} from "./core";
