/**
 * Shared Centrifuge connection pool.
 *
 * Instead of opening one WebSocket per stream (200 connections for 200 streams),
 * we maintain ONE Centrifuge connection per shard WebSocket URL.  All streams on
 * the same shard share a single connection; each stream gets its own
 * ``newSubscription`` on that connection.
 *
 * This keeps the browser well below the per-origin WebSocket connection limit
 * (Firefox default: 200) regardless of the concurrency count.
 */

import { Centrifuge } from "centrifuge";

// Module-level map: ws_url → shared Centrifuge client.
const _shardClients = new Map<string, Centrifuge>();

/**
 * Return the existing shared Centrifuge instance for `wsUrl`, creating and
 * connecting a new one if none exists (or the previous one is disconnected).
 *
 * The `connectionToken` is a per-user JWT with a long TTL (≥ 1 h); it is the
 * same for all streams belonging to the same user, so reusing it across streams
 * is safe.
 */
export function getOrCreateShardClient(wsUrl: string, connectionToken: string): Centrifuge {
  const existing = _shardClients.get(wsUrl);
  if (existing) return existing;

  const client = new Centrifuge(wsUrl, { token: connectionToken });

  client.on("disconnected", (ctx) => {
    if (ctx.code !== 0) {
      console.warn(
        "[centrifugo] shared client disconnected code=%d reason=%s url=%s",
        ctx.code,
        ctx.reason,
        wsUrl,
      );
      // centrifuge-js auto-reconnects on unexpected disconnects (code != 0).
      // Keep the map entry so existing subscriptions survive on this same
      // instance — removing it here would cause the next getOrCreateShardClient
      // call to spawn a duplicate client with no subscriptions.
      return;
    }
    // Explicit disconnect (code 0) — remove stale entry so the pool stays clean.
    // resetShardClients() already calls _shardClients.clear() synchronously
    // before disconnect() is called, so by the time this event fires the entry
    // is usually already gone and this is a no-op.
    if (_shardClients.get(wsUrl) === client) {
      _shardClients.delete(wsUrl);
    }
  });

  client.on("error", (ctx) => {
    console.warn("[centrifugo] shared client error url=%s", wsUrl, ctx);
  });

  _shardClients.set(wsUrl, client);
  client.connect();
  return client;
}

/**
 * Disconnect all shared clients and clear the pool.
 * Call this when a test run completes (handleComplete / handleRestart) to
 * release WebSocket connections eagerly rather than waiting for the browser to
 * close them on GC.
 */
export function resetShardClients(): void {
  _shardClients.forEach((c) => c.disconnect());
  _shardClients.clear();
}
