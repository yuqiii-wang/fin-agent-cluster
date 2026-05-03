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
  const url = `${BASE}/auth/centrifugo/token?thread_id=${encodeURIComponent(threadId)}`;
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
  /** Fired when a node starts — carries topology (parent_node_execution_id). */
  onNodeInput?: (data: unknown) => void;
  /** Fired when a node finishes — carries output + elapsed_ms. */
  onNodeOutput?: (data: unknown) => void;
  /** Fired when a node's lifecycle status changes (node_status SSE event). */
  onNodeStatus?: (data: unknown) => void;
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
    case "node_input":            handlers.onNodeInput?.(data); break;
    case "node_output":           handlers.onNodeOutput?.(data); break;
    case "node_status":           handlers.onNodeStatus?.(data); break;
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
 * @param options   `recoverHistory` (default true) — when false the subscription
 *                  omits the `since` field so Centrifugo does NOT replay channel
 *                  history. Use `false` for resume streams to avoid re-processing
 *                  stale `done` / `cancelled` events from the previous run.
 * @returns Cleanup function that disconnects the WebSocket.
 */
export function openStream(
  threadId: string,
  userToken: string,
  handlers: StreamHandlers,
  options: { recoverHistory?: boolean } = {},
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

      const recoverHistory = options.recoverHistory !== false;

      // If a previous subscription for this channel still exists in the shared
      // client registry (e.g. after unsubscribe on cancel/done), remove it before
      // creating a new one.  centrifuge.newSubscription() throws DuplicateSubscriptionError
      // if the same channel is registered twice on the same client.
      const existingSub = centrifuge.getSubscription(channel);
      if (existingSub) {
        existingSub.unsubscribe();
        existingSub.removeAllListeners();
        centrifuge.removeSubscription(existingSub);
      }

      sub = centrifuge.newSubscription(channel, {
        token: subscription_token,
        recoverable: recoverHistory,
        ...(recoverHistory ? { since: { epoch: '', offset: 0 } } : {}),
      });

      sub.on("publication", (ctx) => {
        dispatch(ctx.data, handlers);
      });

      sub.on("error", (ctx) => {
        const code = ctx.error?.code;
        const temporary = ctx.error?.temporary ?? true;
        console.warn("[stream] subscription error channel=%s threadId=%s code=%s temporary=%s msg=%s",
          channel, threadId, code, temporary, ctx.error?.message);
        // Non-temporary (fatal) subscription errors indicate permanent failure — the
        // subscription will NOT be retried by centrifuge-js.  Surface this as onFailed
        // so the session UI can show an error state rather than hanging indefinitely.
        if (!temporary && !closed) {
          closed = true;
          console.error(
            "[stream] fatal subscription error — reporting centrifugo_token_error channel=%s threadId=%s code=%s",
            channel, threadId, code,
          );
          handlers.onFailed?.({
            event: "failed",
            message: `Centrifugo subscription failed (code ${code}): ${ctx.error?.message ?? "unknown"}`,
            error: "centrifugo_token_error",
          });
        }
      });

      sub.on("subscribed", () => {
        // All channel history has been delivered as publication events at this point.
        // Signal callers so they can poll backend status if no lifecycle events arrived.
        handlers.onSubscribed?.();
      });

      sub.on("unsubscribed", (ctx) => {
        // Only propagate for unexpected server-side unsubscriptions.
        // manualClose is set by cleanup() before calling sub.unsubscribe(), so
        // that path is suppressed.
        if (!manualClose && !closed) {
          console.warn(
            "[stream] subscription unsubscribed unexpectedly channel=%s threadId=%s code=%d",
            channel, threadId, ctx.code,
          );
          // Server-side auth rejection (Centrifugo codes 100–111 are centrifugo
          // protocol errors; codes >= 100 are server-initiated with a specific reason).
          // Treat as centrifugo_token_error so the UI surfaces an actionable error.
          const isServerAuthError = ctx.code > 0;
          closed = true;
          if (isServerAuthError) {
            handlers.onFailed?.({
              event: "failed",
              message: `Centrifugo subscription closed by server (code ${ctx.code})`,
              error: "centrifugo_token_error",
            });
          } else {
            handlers.onClose?.();
          }
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
