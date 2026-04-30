import { ackQuery } from "./queries";

/**
 * Creates a pair of SSE event handlers that implement the query ACK handshake.
 *
 * The handshake is identical for all query types (normal, perf-test):
 * once `query_ack_confirmed` arrives the client stops retrying.
 *
 * @param threadId  - Thread to ACK.
 * @param userToken - Guest user token sent as `X-User-Token`.
 * @param label     - Log prefix for debug output, e.g. `"useStreamSession"`.
 */
export function createAckHandlers(
  threadId: string,
  userToken: string,
  label: string,
): {
  onQueryReceived: (data: unknown) => void;
  onQueryAckConfirmed: (data: unknown) => void;
} {
  let ackInFlight = false;
  let ackConfirmed = false;

  return {
    onQueryReceived: (_data: unknown) => {
      if (ackConfirmed || ackInFlight) return;
      ackInFlight = true;
      ackQuery(threadId, userToken)
        .then(() => {})
        .catch((err) => console.warn("[%s] ACK failed thread_id=%s", label, threadId, err))
        .finally(() => { ackInFlight = false; });
    },
    onQueryAckConfirmed: (_data: unknown) => {
      ackConfirmed = true;
    },
  };
}
