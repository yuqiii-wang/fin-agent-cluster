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
import { useLatestRef } from './refUtils';
import { createLlmClientBundle } from '../api/centrifugoLlmClient';

interface Options {
  llmInfo: SseInfo | null;
  onToken: (taskId: string, token: string, seq: number) => void;
  /** Set to true once the thread reaches a terminal state. */
  done: boolean;
  /**
   * When false the hook defers the MQ connection until the backend
   * stream_start handshake is confirmed.  Defaults to true (connect
   * immediately, e.g. when recovering a history thread).
   */
  enabled?: boolean;
}

export function useCentrifugoLlm({ llmInfo, onToken, done, enabled = true }: Options): void {
  const cfRef = useRef<Centrifuge | null>(null);
  const subRef = useRef<Subscription | null>(null);
  const onTokenRef = useLatestRef(onToken);

  useEffect(() => {
    if (!llmInfo || done || !enabled) return;

    // Same deferred-microtask pattern as useCentrifugoSse: prevents React
    // StrictMode from opening and immediately closing the WebSocket during
    // its synchronous effect → cleanup → effect double-invoke cycle.
    let cancelled = false;

    Promise.resolve().then(() => {
      if (cancelled) return;

      const { cf, sub } = createLlmClientBundle(llmInfo);

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
  }, [llmInfo, done, enabled]);
}
