/**
 * sendDoneAck — client-side done acknowledgement.
 *
 * Called by DoneConditionGuard's onReady callback after all drain conditions
 * are satisfied (or the drain window expires).  Notifies the backend that the
 * client has successfully received and processed the terminal `done` event,
 * allowing the backend to record the confirmation for diagnostics and trigger
 * any final Redis cleanup that was deferred until client confirmation.
 *
 * Failures are non-fatal: the SSE session is already functionally closed on
 * both sides.  Callers should `.catch(() => {})` if they do not want the
 * rejected promise to propagate.
 *
 * sendStatusAck — client-side query_status phase acknowledgement.
 *
 * Called whenever the frontend successfully processes a `query_status` event
 * (phase = received | preparing | ingesting | digesting).  Marks the phase as
 * ACKed in the Redis query-status ACK store; the assistant verifier skips
 * re-delivery for ACKed phases.
 *
 * Failures are non-fatal and should be silently ignored.
 */

import { BASE } from "../../../../api/config";

export interface DoneAckPayload {
  /** The terminal status the client observed (e.g. "completed", "failed", "timeout"). */
  status: string;
}

export interface DoneAckResponse {
  acknowledged: boolean;
  thread_id: string;
}

export interface StatusAckPayload {
  /** The phase being acknowledged, e.g. "received", "preparing". */
  phase: string;
  /**
   * True when this ACK is triggered by an assistant-verifier re-delivery
   * (the original ACK was not confirmed).  Kong uses the `X-Double-Check`
   * request header to pin these requests to the assistant upstream.
   */
  is_double_check?: boolean;
}

export interface StatusAckResponse {
  acknowledged: boolean;
  thread_id: string;
  phase: string;
}

/**
 * Send a done-ACK to the backend for the given thread.
 *
 * @param threadId - LangGraph thread UUID.
 * @param token    - Bearer token for the user (sent as X-User-Token header).
 *                   Pass null to omit the header (unauthenticated sessions).
 * @param status   - Terminal status the client confirmed, e.g. "completed".
 *
 * @throws Error when the HTTP response is not 2xx.
 */
export async function sendDoneAck(
  threadId: string,
  token: string | null,
  status: string,
): Promise<DoneAckResponse> {
  const headers: Record<string, string> = {
    "Content-Type": "application/json",
  };
  if (token) {
    headers["X-User-Token"] = token;
  }

  const res = await fetch(`${BASE}/stream/${threadId}/done-ack`, {
    method: "POST",
    headers,
    body: JSON.stringify({ status } satisfies DoneAckPayload),
  });

  if (!res.ok) {
    throw new Error(`done-ack HTTP ${res.status} thread_id=${threadId}`);
  }

  return res.json() as Promise<DoneAckResponse>;
}

/**
 * Acknowledge a ``query_status`` phase event to the backend.
 *
 * Fire-and-forget: callers must `.catch(() => {})` — failures are non-fatal.
 *
 * @param threadId      - LangGraph thread UUID.
 * @param phase         - Phase label, e.g. "received", "preparing".
 * @param token         - Bearer token; pass null to omit the header.
 * @param isDoubleCheck - Pass `true` when this ACK is a retry triggered by the
 *                        assistant verifier re-delivery.  Adds
 *                        `X-Double-Check: true` so Kong routes the request
 *                        explicitly to the assistant upstream.
 */
export async function sendStatusAck(
  threadId: string,
  phase: string,
  token: string | null,
  isDoubleCheck = false,
): Promise<StatusAckResponse> {
  const headers: Record<string, string> = {
    "Content-Type": "application/json",
  };
  if (token) {
    headers["X-User-Token"] = token;
  }
  if (isDoubleCheck) {
    headers["X-Double-Check"] = "true";
  }

  const res = await fetch(`${BASE}/stream/${threadId}/status-ack`, {
    method: "POST",
    headers,
    body: JSON.stringify({ phase, ...(isDoubleCheck && { is_double_check: true }) } satisfies StatusAckPayload),
  });

  if (!res.ok) {
    throw new Error(`status-ack HTTP ${res.status} thread_id=${threadId} phase=${phase}`);
  }

  return res.json() as Promise<StatusAckResponse>;
}
