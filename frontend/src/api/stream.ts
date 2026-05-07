/**
 * Centrifugo WebSocket streaming client — two-tier architecture.
 *
 * Tier 1: centrifugo-sse-0/1  — SSE lifecycle events, shard-routed by SHA-256(threadId) % 2.
 *   Channel: thread:{threadId}
 *   Events:  started, completed, failed, cancelled, done, query_*, node_*, stream_*
 *   Usage:   openSseStream(threadId, userToken, { onStarted, onDone, ... })
 *
 * Tier 2: centrifugo-token-0/1  — LLM token streaming (shard-routed, optional).
 *   Channel: thread:{threadId}
 *   Events:  token, token_batch
 *   Usage:   openTokenStream(threadId, userToken, { onToken, onTokenBatch })
 *
 * Both use the shared Centrifuge connection pool (one WS per unique ws_url).
 * The backend returns the correct shard ws_url from the token endpoints.
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

export interface CentrifugoSseTokenResponse {
  ws_url: string;
  connection_token: string;
  subscription_token: string;
  shard_index: number;
  channel: string;
}

/** Fetch token-stream Centrifugo JWTs (centrifugo-0/1, shard-routed). */
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

/** Fetch SSE lifecycle Centrifugo JWTs (centrifugo-sse-0/1, shard-routed by thread_id). */
export async function fetchCentrifugoSseToken(
  threadId: string,
  userToken: string
): Promise<CentrifugoSseTokenResponse> {
  const url = `${BASE}/auth/centrifugo/sse-token?thread_id=${encodeURIComponent(threadId)}`;
  const res = await fetch(url, {
    headers: { "X-User-Token": userToken },
  });
  if (!res.ok) throw new Error(`HTTP ${res.status} fetching Centrifugo SSE token`);
  return res.json();
}

// ── Stream event handlers ────────────────────────────────────────────────────

export interface StreamHandlers {
  /** Lifecycle events (delivered via centrifugo-sse-0/1, shard-routed) */
  onStarted?: (data: unknown) => void;
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
  onNodeInput?: (data: unknown) => void;
  onNodeOutput?: (data: unknown) => void;
  onNodeStatus?: (data: unknown) => void;
  onGraphTopologyInit?: (data: unknown) => void;
  /** Token events (delivered via centrifugo-0/1) */
  onToken?: (data: unknown) => void;
  onTokenBatch?: (data: unknown) => void;
  /**
   * Fired when the centrifugo-sse-{shard} subscription becomes active and all channel
   * history has been delivered.  Use this to poll backend status if no lifecycle
   * events arrived from history.
   */
  onSubscribed?: () => void;
  onClose?: () => void;
}

/** Dispatch a lifecycle publication (centrifugo-sse-0/1) to the correct handler. */
function dispatchLifecycle(data: unknown, handlers: StreamHandlers): void {
  if (!data || typeof data !== "object") return;
  const ev = (data as Record<string, unknown>)["event"] as string | undefined;
  if (!ev) return;

  switch (ev) {
    case "started":             handlers.onStarted?.(data); break;
    case "ingest_complete":     handlers.onIngestComplete?.(data); break;
    case "stream_stopped":      handlers.onStreamStopped?.(data); break;
    case "stream_complete":     handlers.onStreamComplete?.(data); break;
    case "completed":           handlers.onCompleted?.(data); break;
    case "failed":              handlers.onFailed?.(data); break;
    case "cancelled":           handlers.onCancelled?.(data); break;
    case "done":                handlers.onDone?.(data); break;
    case "query_status":        handlers.onQueryStatus?.(data); break;
    case "query_received":      handlers.onQueryReceived?.(data); break;
    case "query_ack_confirmed": handlers.onQueryAckConfirmed?.(data); break;
    case "node_input":          handlers.onNodeInput?.(data); break;
    case "node_output":         handlers.onNodeOutput?.(data); break;
    case "node_status":         handlers.onNodeStatus?.(data); break;
    case "graph_topology_init": handlers.onGraphTopologyInit?.(data); break;
    default:
      break;
  }
}

/** Dispatch a token publication (centrifugo-0/1) to the correct handler. */
function dispatchToken(data: unknown, handlers: StreamHandlers): void {
  if (!data || typeof data !== "object") return;
  const ev = (data as Record<string, unknown>)["event"] as string | undefined;
  if (!ev) return;

  switch (ev) {
    case "token":       handlers.onToken?.(data); break;
    case "token_batch": handlers.onTokenBatch?.(data); break;
    default:
      break;
  }
}
// ── Shared subscription factory ──────────────────────────────────────────────

/**
 * Internal helper — creates a Centrifuge subscription for *channel* on the
 * client at *wsUrl* and wires *onPublication*, *onSubscribed*, *onError*, and
 * *onUnsubscribed* handlers.  Returns a cleanup function.
 */
function _createSubscription(
  wsUrl: string,
  connectionToken: string,
  subscriptionToken: string,
  channel: string,
  recoverHistory: boolean,
  onPublication: (data: unknown) => void,
  onSubscribed: (() => void) | undefined,
  onFatal: (msg: string) => void,
  onUnexpectedClose: (() => void) | undefined,
  logPrefix: string,
  threadId: string,
): () => void {
  const centrifuge = getOrCreateShardClient(wsUrl, connectionToken);

  const existingSub = centrifuge.getSubscription(channel);
  if (existingSub) {
    existingSub.unsubscribe();
    existingSub.removeAllListeners();
    centrifuge.removeSubscription(existingSub);
  }

  const sub = centrifuge.newSubscription(channel, {
    token: subscriptionToken,
    recoverable: recoverHistory,
    ...(recoverHistory ? { since: { epoch: "", offset: 0 } } : {}),
  });

  let manualClose = false;
  let closed = false;

  const cleanup = () => {
    if (closed) return;
    closed = true;
    manualClose = true;
    sub.unsubscribe();
    sub.removeAllListeners();
  };

  sub.on("publication", (ctx) => {
    onPublication(ctx.data);
  });

  sub.on("error", (ctx) => {
    const code = (ctx.error as any)?.code;
    const temporary = (ctx.error as any)?.temporary ?? true;
    console.warn(
      "[%s] subscription error channel=%s threadId=%s code=%s temporary=%s msg=%s",
      logPrefix, channel, threadId, code, temporary, (ctx.error as any)?.message,
    );
    if (!temporary && !closed) {
      closed = true;
      onFatal(
        `Centrifugo subscription failed (code ${code}): ${(ctx.error as any)?.message ?? "unknown"}`,
      );
    }
  });

  sub.on("subscribed", () => {
    onSubscribed?.();
  });

  sub.on("unsubscribed", (ctx) => {
    if (!manualClose && !closed) {
      console.warn(
        "[%s] subscription unsubscribed unexpectedly channel=%s threadId=%s code=%d",
        logPrefix, channel, threadId, ctx.code,
      );
      closed = true;
      if (ctx.code > 0) {
        onFatal(`Centrifugo subscription closed by server (code ${ctx.code})`);
      } else {
        onUnexpectedClose?.();
      }
    }
  });

  sub.subscribe();
  return cleanup;
}

// ── openSseStream ─────────────────────────────────────────────────────────────

/**
 * Connect to **centrifugo-sse-{shard}** and subscribe to the ``thread:{threadId}``
 * channel for all SSE lifecycle events (started, completed, failed, done,
 * query_*, node_*, stream_*).  Token events are NOT delivered here.
 *
 * @param threadId  LangGraph thread UUID.
 * @param userToken X-User-Token from localStorage.
 * @param handlers  Event callbacks.  `onToken`/`onTokenBatch` are ignored here.
 * @param options   `recoverHistory` (default true).
 * @returns Cleanup function that unsubscribes.
 */
export function openSseStream(
  threadId: string,
  userToken: string,
  handlers: StreamHandlers,
  options: { recoverHistory?: boolean } = {},
): () => void {
  let cleanup: (() => void) | null = null;
  let closed = false;

  const earlyCleanup = () => {
    closed = true;
    cleanup?.();
  };

  const recoverHistory = options.recoverHistory !== false;

  fetchCentrifugoSseToken(threadId, userToken)
    .then(({ ws_url, connection_token, subscription_token, channel }) => {
      if (closed) {
        console.error(
          "[sse-stream] CLOSED GUARD: cleanup before connect threadId=%s",
          threadId,
        );
        return;
      }

      const wsScheme = window.location.protocol === "https:" ? "wss:" : "ws:";
      const localWsUrl = ws_url.replace(
        /^wss?:\/\/[^/]+/,
        `${wsScheme}//${window.location.host}`,
      );

      cleanup = _createSubscription(
        localWsUrl,
        connection_token,
        subscription_token,
        channel,
        recoverHistory,
        (data) => dispatchLifecycle(data, handlers),
        handlers.onSubscribed,
        (msg) => handlers.onFailed?.({ event: "failed", message: msg, error: "centrifugo_token_error" }),
        handlers.onClose,
        "sse-stream",
        threadId,
      );

      console.info(
        "[sse-stream] subscribed threadId=%s channel=%s ws=%s",
        threadId, channel, localWsUrl,
      );
    })
    .catch((err) => {
      if (closed) return;
      console.error("[sse-stream] failed to fetch SSE token threadId=%s", threadId, err);
      handlers.onFailed?.({ event: "failed", message: String(err), error: "centrifugo_token_error" });
    });

  return earlyCleanup;
}

// ── openTokenStream ───────────────────────────────────────────────────────────

/**
 * Connect to **centrifugo-0/1** (shard-routed) and subscribe to the
 * ``thread:{threadId}`` channel for LLM token events only.
 *
 * Token events are published by Centrifugo's built-in Redis Stream consumer
 * from ``fin:llm:tokens``.  Only ``onToken`` and ``onTokenBatch`` are invoked.
 *
 * @param threadId  LangGraph thread UUID.
 * @param userToken X-User-Token from localStorage.
 * @param handlers  Only `onToken` and `onTokenBatch` are used.
 * @param options   `recoverHistory` (default false — tokens are ephemeral).
 * @returns Cleanup function that unsubscribes.
 */
export function openTokenStream(
  threadId: string,
  userToken: string,
  handlers: Pick<StreamHandlers, "onToken" | "onTokenBatch">,
  options: { recoverHistory?: boolean } = {},
): () => void {
  let cleanup: (() => void) | null = null;
  let closed = false;

  const earlyCleanup = () => {
    closed = true;
    cleanup?.();
  };

  const recoverHistory = options.recoverHistory === true;

  fetchCentrifugoToken(threadId, userToken)
    .then(({ ws_url, connection_token, subscription_token, channel, shard_index }) => {
      if (closed) return;

      const wsScheme = window.location.protocol === "https:" ? "wss:" : "ws:";
      const localWsUrl = ws_url.replace(
        /^wss?:\/\/[^/]+/,
        `${wsScheme}//${window.location.host}`,
      );

      cleanup = _createSubscription(
        localWsUrl,
        connection_token,
        subscription_token,
        channel,
        recoverHistory,
        (data) => dispatchToken(data, handlers),
        undefined,
        (msg) => console.warn("[token-stream] fatal error threadId=%s: %s", threadId, msg),
        undefined,
        "token-stream",
        threadId,
      );

      console.info(
        "[token-stream] subscribed threadId=%s channel=%s ws=%s shard=%d",
        threadId, channel, localWsUrl, shard_index,
      );
    })
    .catch((err) => {
      if (closed) return;
      console.warn("[token-stream] failed to fetch token threadId=%s", threadId, err);
    });

  return earlyCleanup;
}

// ── openStream (removed — use openSseStream + openTokenStream) ────────────────
// openStream has been replaced by the two-tier approach above.
// Call openSseStream() for lifecycle events and openTokenStream() for tokens.
