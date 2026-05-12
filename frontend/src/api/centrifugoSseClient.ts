/**
 * centrifugoSseClient — factory for the SSE lifecycle Centrifugo tier.
 *
 * The SSE tier (centrifugo-sse-{shard}) carries all lifecycle events:
 * started, completed, done, query_*, node_*, stream_*.  The backend
 * waits for ACK RPCs sent back over this same connection.
 *
 * History recovery is enabled by default so messages published before the
 * subscription connected are replayed on connect.
 * Set `withHistory = false` for presence-only channels that do not need
 * event replay (e.g. user:{userId} presence subscriptions).
 */

import { Centrifuge, Subscription } from 'centrifuge';
import type { SseInfo } from '../types';

export interface SseClientBundle {
  cf: Centrifuge;
  sub: Subscription;
}

/**
 * Creates a Centrifuge client and subscription configured for the SSE tier.
 *
 * The caller is responsible for attaching publication/rpc handlers and
 * calling `sub.subscribe()` / `cf.connect()`.
 *
 * @param info - Connection bootstrap info from the sse-token endpoint.
 * @param withHistory - Request history recovery from offset 0 (default: true).
 *   Set false for presence channels that do not replay event history.
 */
export function createSseClientBundle(info: SseInfo, withHistory = true): SseClientBundle {
  const cf = new Centrifuge(info.ws_url, {
    token: info.connection_token,
  });

  const sub = cf.newSubscription(info.channel, {
    token: info.subscription_token,
    ...(withHistory ? { since: { offset: 0, epoch: '' } } : {}),
  });

  return { cf, sub };
}
