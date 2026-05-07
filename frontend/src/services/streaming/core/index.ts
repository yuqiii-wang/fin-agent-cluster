/**
 * streaming/core — shared streaming session infrastructure.
 *
 * Contains all reusable streaming lifecycle logic used by both perf-test
 * sessions and single-test sessions:
 *
 *   lifecycle/          — DoneConditionGuard + done/status ACK senders
 *   errors/             — UI-side streaming error codes
 *   sessionState.ts     — mutable per-session closure state
 *   sessionHelpers.ts   — dequeue / terminate / drainGuard helpers
 *   phaseHandlers.ts    — query_status / ingest_complete / started / completed handlers
 *   tokenHandler.ts     — perf_token_batch buffering + auto-complete logic
 *   terminalHandlers.ts — done / failed / cancelled / close handlers
 */

// ── Lifecycle ────────────────────────────────────────────────────────────────
export { DoneConditionGuard, sendDoneAck, sendStatusAck } from "./lifecycle";
export type {
  StreamLifecyclePhase,
  DoneConditionFn,
  DoneGuardOptions,
  DoneAckPayload,
  DoneAckResponse,
  StatusAckPayload,
  StatusAckResponse,
} from "./lifecycle";

// ── Errors ───────────────────────────────────────────────────────────────────
export { UI_STREAMING_ERRORS, getErrorDescription } from "./errors";

// ── Token batch flush (concurrency streaming) ────────────────────────────────
export { useTokenBatchFlush } from "./useTokenBatchFlush";
export type { UseTokenBatchFlushReturn, DrainedBatch } from "./useTokenBatchFlush";

// ── Shared streaming output component (now lives in OutputViewer/renderers) ──
export { StreamingTaskOutput } from "../../../components/OutputViewer/renderers/StreamingTaskOutput";

// ── On-demand task stream hook ────────────────────────────────────────────────
export { useTaskStream } from "./useTaskStream";
export type { UseTaskStreamReturn, TaskStreamPhase } from "./useTaskStream";

// ── Session state ─────────────────────────────────────────────────────────────
export { createSessionClosureState } from "./sessionState";
export type { SessionClosureState } from "./sessionState";

// ── Session helpers ───────────────────────────────────────────────────────────
export { createSessionHelpers } from "./sessionHelpers";
export type { SessionHelpers, SessionHelperDeps } from "./sessionHelpers";

// ── Phase handlers ────────────────────────────────────────────────────────────
export { createPhaseHandlers } from "./phaseHandlers";
export type { PhaseHandlerDeps } from "./phaseHandlers";

// ── Token handler ─────────────────────────────────────────────────────────────
export { createTokenHandler } from "./tokenHandler";
export type { TokenHandlerDeps } from "./tokenHandler";

// ── Terminal handlers ─────────────────────────────────────────────────────────
export { createTerminalHandlers } from "./terminalHandlers";
export type { TerminalHandlerDeps } from "./terminalHandlers";
