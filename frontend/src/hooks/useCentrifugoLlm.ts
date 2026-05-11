/**
 * useCentrifugoLlm — subscribe to the LLM token Centrifugo tier.
 *
 * Connects to centrifugo-llm-{shard} using bootstrap info from the
 * submit_query response.  Fires onToken for every individual token published
 * to the thread channel, routing by task_id so a single shared connection
 * serves all tasks in the thread.
 */

import { useEffect, useRef } from 'react';
import { Centrifuge, Subscription } from 'centrifuge';
import type { SseInfo } from '../types';

interface Options {
  llmInfo: SseInfo | null;
  onToken: (taskId: string, token: string, seq: number) => void;
  /** Set to true once the thread reaches a terminal state. */
  done: boolean;
}

export function useCentrifugoLlm({ llmInfo, onToken, done }: Options): void {
  const cfRef = useRef<Centrifuge | null>(null);
  const subRef = useRef<Subscription | null>(null);
  const onTokenRef = useRef(onToken);
  onTokenRef.current = onToken;

  useEffect(() => {
    if (!llmInfo || done) return;

    // Same deferred-microtask pattern as useCentrifugoSse: prevents React
    // StrictMode from opening and immediately closing the WebSocket during
    // its synchronous effect → cleanup → effect double-invoke cycle.
    let cancelled = false;

    Promise.resolve().then(() => {
      if (cancelled) return;

      const cf = new Centrifuge(llmInfo.ws_url, {
        token: llmInfo.connection_token,
      });

      const sub = cf.newSubscription(llmInfo.channel, {
        token: llmInfo.subscription_token,
      });

      // Store refs before connecting so cleanup can reach them.
      cfRef.current = cf;
      subRef.current = sub;

      sub.on('publication', (ctx) => {
        const ev = ctx.data as Record<string, unknown>;
        if (
          ev['event'] === 'token' &&
          typeof ev['task_id'] === 'string' &&
          typeof ev['token'] === 'string'
        ) {
          onTokenRef.current(
            ev['task_id'] as string,
            ev['token'] as string,
            typeof ev['seq'] === 'number' ? (ev['seq'] as number) : 0,
          );
        }
      });

      sub.subscribe();
      cf.connect();
    });

    return () => {
      cancelled = true;
      subRef.current?.unsubscribe();
      cfRef.current?.disconnect();
      cfRef.current = null;
      subRef.current = null;
    };
  }, [llmInfo, done]);
}
