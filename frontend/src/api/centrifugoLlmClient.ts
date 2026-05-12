/**
 * centrifugoLlmClient — factory for the LLM token streaming Centrifugo tier.
 *
 * The LLM tier (centrifugo-llm-{shard}) carries only token publications.
 * History recovery is enabled by default so tokens published in the gap
 * between stream_start ACK and subscription established are replayed.
 * Set `withHistory = false` for callers that connect live with no catch-up.
 */

import { Centrifuge, Subscription } from 'centrifuge';
import type { SseInfo } from '../types';

export interface LlmClientBundle {
  cf: Centrifuge;
  sub: Subscription;
}

/**
 * Creates a connected Centrifuge client and subscription for the LLM tier.
 *
 * The caller is responsible for attaching publication handlers and calling
 * `sub.subscribe()` / `cf.connect()`.
 *
 * @param info - Connection bootstrap info from the llm-token endpoint.
 * @param withHistory - Request history recovery from offset 0 (default: true).
 */
export function createLlmClientBundle(info: SseInfo, withHistory = true): LlmClientBundle {
  const cf = new Centrifuge(info.ws_url, {
    token: info.connection_token,
  });

  const sub = cf.newSubscription(info.channel, {
    token: info.subscription_token,
    ...(withHistory ? { since: { offset: 0, epoch: '' } } : {}),
  });

  return { cf, sub };
}
