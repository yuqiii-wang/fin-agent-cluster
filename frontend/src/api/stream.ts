/**
 * Centrifugo WebSocket streaming client.
 *
 * Replaces the previous EventSource/SSE implementation.  All real-time events
 * (token, started, completed, failed, cancelled, done, query_* perf_*) arrive
 * on the ``thread:{threadId}`` Centrifugo channel.
 *
 * Usage:
 *   const cleanup = openStream(threadId, { onToken, onDone, ... });
 *   // later:
 *   cleanup();
 */

import type { Subscription } from "centrifuge";
import { getOrCreateShardClient } from "./centrifugoClient";
import { BASE, KONG_ORIGIN } from "./config";

// ── Token bootstrap ──────────────────────────────────────────────────────────

export interface CentrifugoTokenResponse {
  ws_url: string;
  connection_token: string;
  subscription_token: string;
  shard_index: number;
  channel: string;
}

/** Fetch Centrifugo connection + subscription tokens from FastAPI. */
export async function fetchCentrifugoToken(
  threadId: string,
  userToken: string
): Promise<CentrifugoTokenResponse> {
  const url = `${BASE}/centrifugo/token?thread_id=${encodeURIComponent(threadId)}`;
  const res = await fetch(url, {
    headers: { "X-User-Token": userToken },
  });
  if (!res.ok) throw new Error(`HTTP ${res.status} fetching Centrifugo token`);
  return res.json();
}

// ── Stream event handlers ────────────────────────────────────────────────────

export interface StreamHandlers {
  onStarted?: (data: unknown) => void;
  onToken?: (data: unknown) => void;
  onTokenBatch?: (data: unknown) => void;
  onIngestComplete?: (data: unknown) => void;
  onStreamStopped?: (data: unknown) => void;
  onStreamComplete?: (data: unknown) => void;
  onCompleted?: (data: unknown) => void;
  onFailed?: (data: unknown) => void;
  onCancelled?: (data: unknown) => void;
  onDone?: (data: unknown) => void;
  onQueryStatus?: (data: unknown) => void;
  onQueryReceived?: (data: unknown) => void;
  onQueryAckConfirmed?: (data: unknown) => void;
  /**
   * Fired when the Centrifugo subscription becomes active and all channel history
   * has been delivered as `publication` events.  Use this as the signal to
   * proactively poll `GET /users/query/{threadId}` if no lifecycle events were
   * received from history (i.e. the query is already past the `received` phase).
   */
  onSubscribed?: () => void;
  onClose?: () => void;
}

/** Dispatch a Centrifugo publication payload to the correct handler. */
function dispatch(data: unknown, handlers: StreamHandlers): void {
  if (!data || typeof data !== "object") return;
  const ev = (data as Record<string, unknown>)["event"] as string | undefined;
  if (!ev) return;

  switch (ev) {
    case "started":               handlers.onStarted?.(data); break;
    case "token":                 handlers.onToken?.(data); break;
    case "token_batch":          handlers.onTokenBatch?.(data); break;
    case "ingest_complete":       handlers.onIngestComplete?.(data); break;
    case "stream_stopped":        handlers.onStreamStopped?.(data); break;
    case "stream_complete":       handlers.onStreamComplete?.(data); break;
    case "completed":             handlers.onCompleted?.(data); break;
    case "failed":                handlers.onFailed?.(data); break;
    case "cancelled":             handlers.onCancelled?.(data); break;
    case "done":                  handlers.onDone?.(data); break;
    case "query_status":          handlers.onQueryStatus?.(data); break;
    case "query_received":        handlers.onQueryReceived?.(data); break;
    case "query_ack_confirmed":   handlers.onQueryAckConfirmed?.(data); break;
    default:
      break;
  }
}

// ── Main openStream function ─────────────────────────────────────────────────

/**
 * Connect to Centrifugo and subscribe to the ``thread:{threadId}`` channel.
 *
 * Fetches JWT tokens from FastAPI, establishes a WebSocket connection to the
 * correct Centrifugo shard, and invokes callbacks on publication events.
 *
 * @param threadId  LangGraph thread UUID.
 * @param userToken X-User-Token from localStorage.
 * @param handlers  Event callbacks.
 * @returns Cleanup function that disconnects the WebSocket.
 */
export function openStream(
  threadId: string,
  userToken: string,
  handlers: StreamHandlers
): () => void {
  let sub: Subscription | null = null;
  let closed = false;
  // Set before calling sub.unsubscribe() so the unsubscribed event handler
  // can distinguish a manual cleanup from an unexpected server-side close.
  let manualClose = false;

  const cleanup = () => {
    if (closed) return;
    closed = true;
    manualClose = true;
    sub?.unsubscribe();
    sub?.removeAllListeners();
    // Do NOT disconnect the shared shard client — other subscriptions are still active.
  };

  // Fetch tokens then connect.
  fetchCentrifugoToken(threadId, userToken)
    .then(({ ws_url, connection_token, subscription_token, channel, shard_index }) => {
      if (closed) {
        // cleanup() was called before the Centrifugo connection could be established
        // (e.g. the session was cancelled or the component unmounted while the token
        // fetch was in flight).  Log so the browser console can surface which streams
        // hit this race and under what circumstances.
        console.error(
          "[stream] CLOSED GUARD: cleanup fired before Centrifugo connect threadId=%s — " +
          "stream will stay at its current status. If this recurs, check for premature " +
          "cleanup calls (freezeAll, handleRestart, or component unmount).",
          threadId,
        );
        return;
      }

      // Rewrite the backend-returned ws_url (Docker-internal hostname) to use
      // the current page origin so the WS upgrade goes through the same proxy
      // that serves the page:
      //  - Dev (Vite proxy):  ws://localhost:3000/centrifugo-{n}/connection/websocket
      //  - Prod (nginx 22332): wss://localhost:22332/centrifugo-{n}/connection/websocket
      // The backend already includes the /centrifugo-{shard}/ path prefix, so
      // only the scheme+host needs to be rewritten.
      const wsScheme = window.location.protocol === "https:" ? "wss:" : "ws:";
      const localWsUrl = ws_url.replace(
        /^wss?:\/\/[^/]+/,
        `${wsScheme}//${window.location.host}`,
      );

      // Reuse (or create) the shared Centrifuge connection for this shard.
      // This keeps the total WebSocket count at 1 per shard regardless of how
      // many concurrent streams are open.
      const centrifuge = getOrCreateShardClient(localWsUrl, connection_token);

      sub = centrifuge.newSubscription(channel, {
        token: subscription_token,
        recoverable: true,
        since: { epoch: '', offset: 0 }, // recover all history on first subscription
      });

      sub.on("publication", (ctx) => {
        dispatch(ctx.data, handlers);
      });

      sub.on("error", (ctx) => {
        console.warn("[stream] subscription error channel=%s threadId=%s code=%s msg=%s",
          channel, threadId, ctx.error?.code, ctx.error?.message);
      });

      sub.on("subscribed", () => {
        // All channel history has been delivered as publication events at this point.
        // Signal callers so they can poll backend status if no lifecycle events arrived.
        handlers.onSubscribed?.();
      });

      sub.on("unsubscribed", (ctx) => {
        // Only propagate onClose for unexpected server-side unsubscriptions.
        // manualClose is set by cleanup() before calling sub.unsubscribe(), so
        // that path is suppressed.
        if (!manualClose && !closed) {
          console.warn(
            "[stream] subscription unsubscribed unexpectedly channel=%s threadId=%s code=%d",
            channel, threadId, ctx.code,
          );
          handlers.onClose?.();
          closed = true;
        }
      });

      sub.subscribe();
      console.info("[stream] Centrifugo subscribed threadId=%s channel=%s ws=%s shard=%d", threadId, channel, localWsUrl, shard_index);
    })
    .catch((err) => {
      if (closed) return;
      console.error("[stream] failed to fetch Centrifugo token threadId=%s", threadId, err);
      handlers.onFailed?.({ event: "failed", message: String(err), error: "centrifugo_token_error" });
    });

  return cleanup;
}
