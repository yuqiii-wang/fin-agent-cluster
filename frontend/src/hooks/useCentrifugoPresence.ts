/**
 * useCentrifugoPresence — maintain a user-level presence subscription.
 *
 * Subscribes to ``user:{userId}`` on the correct centrifugo-sse shard while
 * the app is open.  The backend checks ``presence_stats`` on this channel via
 * ``has_app_viewers`` to detect whether the browser is still open.
 *
 * No publication handler is needed — the subscription itself is the signal.
 */

import { useEffect, useRef } from 'react';
import { Centrifuge, Subscription } from 'centrifuge';
import { getSsePresenceToken } from '../api/auth';
import { createSseClientBundle } from '../api/centrifugoSseClient';

interface Options {
  userId: string | undefined;
}

export function useCentrifugoPresence({ userId }: Options): void {
  const cfRef = useRef<Centrifuge | null>(null);
  const subRef = useRef<Subscription | null>(null);

  useEffect(() => {
    if (!userId) return;

    let cancelled = false;

    Promise.resolve().then(async () => {
      if (cancelled) return;
      try {
        const info = await getSsePresenceToken();
        if (cancelled) return;

        const { cf, sub } = createSseClientBundle(info, false);

        cfRef.current = cf;
        subRef.current = sub;

        sub.subscribe();
        cf.connect();
      } catch {
        // Non-fatal — presence is best-effort; backend defaults to True on error.
      }
    });

    return () => {
      cancelled = true;
      subRef.current?.unsubscribe();
      cfRef.current?.disconnect();
      cfRef.current = null;
      subRef.current = null;
    };
  }, [userId]);
}
