/**
 * useTokenStream — subscribe to LLM token streaming from centrifugo-llm-{shard}.
 *
 * Fetches connection tokens from the backend then connects to the LLM-specific
 * Centrifugo tier.  Buffers incoming tokens in a ref and delivers them via
 * onToken callback.  Fires onEnd when stream_end is received.
 */

import { useEffect, useRef } from 'react';
import { Centrifuge, Subscription } from 'centrifuge';
import { getLlmToken } from '../api/threads';
import { createLlmClientBundle } from '../api/centrifugoLlmClient';
import type { SseEvent } from '../types';
import { useLatestRef } from './refUtils';

interface Options {
  threadId: string;
  taskId: string | null;
  active: boolean;
  onToken: (token: string, seq: number) => void;
  onEnd: (totalTokens: number) => void;
}

export function useTokenStream({ threadId, taskId, active, onToken, onEnd }: Options): void {
  const cfRef = useRef<Centrifuge | null>(null);
  const subRef = useRef<Subscription | null>(null);
  const onTokenRef = useLatestRef(onToken);
  const onEndRef = useLatestRef(onEnd);

  useEffect(() => {
    if (!active || !taskId) return;

    let cancelled = false;

    (async () => {
      try {
        const tok = await getLlmToken(threadId);
        if (cancelled) return;

        const { cf, sub } = createLlmClientBundle(tok, false);

        sub.on('publication', (ctx) => {
          const ev = ctx.data as SseEvent;
          if (ev.event === 'token' && ev.token && ev.seq != null) {
            onTokenRef.current(ev.token, ev.seq);
          } else if (ev.event === 'token_batch' && Array.isArray((ev as unknown as { tokens: unknown[] }).tokens)) {
            for (const t of (ev as unknown as { tokens: Array<{ token: string; seq: number }> }).tokens) {
              onTokenRef.current(t.token, t.seq);
            }
          } else if (ev.event === 'stream_end') {
            onEndRef.current(ev.total_tokens ?? 0);
          }
        });

        sub.subscribe();
        cf.connect();
        cfRef.current = cf;
        subRef.current = sub;
      } catch {
        /* token fetch failed — streaming will degrade gracefully */
      }
    })();

    return () => {
      cancelled = true;
      subRef.current?.unsubscribe();
      cfRef.current?.disconnect();
      cfRef.current = null;
      subRef.current = null;
    };
  }, [active, taskId, threadId]);
}
