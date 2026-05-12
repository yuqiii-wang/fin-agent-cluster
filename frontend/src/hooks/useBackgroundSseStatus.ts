/**
 * useBackgroundSseStatus — lightweight Centrifugo SSE subscriber for
 * background threads (threads running while the user views a different thread).
 *
 * Unlike useCentrifugoSse, this hook:
 *  - Does NOT send ACK RPCs (backend already returned without waiting).
 *  - Only forwards `query_status` events to `onStatusUpdate`.
 *  - Disconnects automatically when a terminal status is received.
 */

import { useEffect, useRef } from 'react';
import { Centrifuge, Subscription } from 'centrifuge';
import type { SseEvent, SseInfo } from '../types';
import { createSseClientBundle } from '../api/centrifugoSseClient';
import { isThreadTerminal } from '../constants/lifecycleStatus';
import { useLatestRef } from './refUtils';

interface Options {
  sseInfo: SseInfo | null;
  onStatusUpdate: (status: string) => void;
}

export function useBackgroundSseStatus({ sseInfo, onStatusUpdate }: Options): void {
  const onStatusUpdateRef = useLatestRef(onStatusUpdate);

  const cfRef = useRef<Centrifuge | null>(null);
  const subRef = useRef<Subscription | null>(null);

  useEffect(() => {
    if (!sseInfo) return;

    let cancelled = false;

    Promise.resolve().then(() => {
      if (cancelled) return;

      const { cf, sub } = createSseClientBundle(sseInfo);

      cfRef.current = cf;
      subRef.current = sub;

      sub.on('publication', (ctx) => {
        const ev = ctx.data as SseEvent;
        if (ev.event === 'query_status' && ev.status) {
          onStatusUpdateRef.current(ev.status);
          if (isThreadTerminal(ev.status)) {
            subRef.current?.unsubscribe();
            cfRef.current?.disconnect();
          }
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
  }, [sseInfo]);
}
