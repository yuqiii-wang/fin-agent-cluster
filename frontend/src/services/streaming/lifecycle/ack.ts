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
 */

import { BASE } from "../../../api/config";

export interface DoneAckPayload {
  /** The terminal status the client observed (e.g. "completed", "failed", "timeout"). */
  status: string;
}

export interface DoneAckResponse {
  acknowledged: boolean;
  thread_id: string;
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
