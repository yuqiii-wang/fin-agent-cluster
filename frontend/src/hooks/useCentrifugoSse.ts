/**
 * useCentrifugoSse — subscribe to the SSE lifecycle Centrifugo tier.
 *
 * Connects to centrifugo-sse-{shard} using the bootstrap info from the
 * submit_query response.  Fires onEvent on every publication.  Sends an
 * ACK back to the backend for events that require acknowledgement by
 * publishing to the same channel (sub.publish), which Centrifugo forwards
 * to the backend publish proxy endpoint.  The publish promise resolving
 * is the confirmation signal — no separate ack_confirmed event needed.
 */

import { useEffect, useRef } from 'react';
import { Centrifuge, Subscription } from 'centrifuge';
import type { SseEvent, SseInfo } from '../types';
import { useLatestRef } from './refUtils';
import { createSseClientBundle } from '../api/centrifugoSseClient';
import { setThreadViewer, clearThreadViewer } from '../api/threads';

interface Options {
  sseInfo: SseInfo | null;
  onEvent: (ev: SseEvent) => void;
  /** Set to true once the thread reaches a terminal state. */
  done: boolean;
}

export function useCentrifugoSse({ sseInfo, onEvent, done }: Options): void {
  const cfRef = useRef<Centrifuge | null>(null);
  const subRef = useRef<Subscription | null>(null);
  const onEventRef = useLatestRef(onEvent);
  // Tracks ack_keys for which the backend has already confirmed receipt.
  // Once an ack_key is confirmed we must not send another ACK for retried
  // copies of the same event, since the backend has already stopped listening.
  const confirmedAckKeysRef = useRef<Set<string>>(new Set());
  // Tracks in-flight ACK publish promises so the cleanup can drain them before
  // disconnecting.  Without this, a `sub.publish()` that was started in the
  // publication handler may fail with code-11 (connection closed) when React
  // tears down the effect synchronously after `isDone` flips to true on the
  // same SSE event that triggered the ACK — causing the backend to exhaust its
  // retry budget without ever receiving the ACK signal.
  const pendingAckPromsRef = useRef<Set<Promise<void>>>(new Set());

  useEffect(() => {
    if (!sseInfo || done) return;

    // thread_id is embedded in the channel as "thread:{threadId}".
    const threadId = sseInfo.channel.replace(/^thread:/, '');

    // Deferred connection via microtask: in React StrictMode the framework
    // runs effect → cleanup → effect synchronously in one scheduler task.
    // By deferring cf.connect() to the next microtask we let the StrictMode
    // cleanup set `cancelled = true` before the WebSocket is ever opened,
    // eliminating the spurious "can't establish" / "interrupted" browser errors
    // that occur when the handshake is torn down mid-flight.
    let cancelled = false;

    Promise.resolve().then(() => {
      if (cancelled) return;

      const { cf, sub } = createSseClientBundle(sseInfo);

      // Store refs before connecting so cleanup can reach them if it fires
      // after this microtask but before the connection is torn down.
      cfRef.current = cf;
      subRef.current = sub;

      // Set the viewer flag before opening the WebSocket.  This ensures the
      // backend sees a live subscriber before publishing the first SSE event
      // with the full ACK retry loop.  The flag is cleared in the cleanup
      // function so stale flags never trigger ACK loops after disconnect.
      setThreadViewer(threadId);

      sub.on('publication', (ctx) => {
        const ev = ctx.data as SseEvent;
        onEventRef.current(ev);

        // ack_confirmed is no longer published as a channel event — ACK
        // confirmation is signalled by the sub.publish() promise resolving.
        // Guard here to silently ignore any stale ack_confirmed events that
        // may exist in Centrifugo history from before the migration.
        if (ev.event === 'ack_confirmed') {
          if (ev.ack_key) confirmedAckKeysRef.current.add(ev.ack_key);
          return;
        }

        // Send ACK for events the backend waits on.
        const tid = (ev.thread_id as string | undefined) ?? threadId;
        // Prefer the backend-provided ack_key (nonce-stamped, unique per invocation)
        // to avoid false-positive deduplication caused by Centrifugo channel history
        // replaying ack_confirmed events from previous graph runs (re-explore / resume).
        const ackKey: string =
          (ev.ack_key as string | undefined) ??
          (ev.task_id
            ? `task:${ev.task_id}:${ev.status ?? ev.event}`
            : ev.node_id
            ? `node:${ev.node_id}:${ev.status ?? ev.event}`
            : `thread:${ev.event}:${ev.status ?? ''}`);

        // Skip if the backend already confirmed this ack_key (retry duplicate).
        if (confirmedAckKeysRef.current.has(ackKey)) {
          return;
        }

        const ackProm: Promise<void> = sub.publish({
          event: 'ack',
          scope: ev.task_id ? 'task' : ev.node_id ? 'node' : 'thread',
          ack_key: ackKey,
          thread_id: tid,
        }).then(() => {
          confirmedAckKeysRef.current.add(ackKey);
        }).catch((err: unknown) => {
          // code 11 = "connection closed" — expected on tab close / navigation.
          if (err && typeof err === 'object' && (err as { code?: number }).code === 11) return;
          console.error('[sse-ack] publish failed event=%s ack_key=%s: %o', ev.event, ackKey, err);
        });

        // Register the in-flight ACK so cleanup can drain it before tearing
        // down the WebSocket.  Guard with !cancelled so we don't accumulate
        // after cleanup has already run (StrictMode double-invoke edge case).
        if (!cancelled) {
          pendingAckPromsRef.current.add(ackProm);
          ackProm.finally(() => pendingAckPromsRef.current.delete(ackProm));
        }
      });

      sub.subscribe();
      cf.connect();
    });

    return () => {
      cancelled = true;
      // Capture local references immediately so a subsequent effect run
      // (e.g. StrictMode re-invoke or sseInfo/done change) can overwrite
      // the shared refs without interfering with this cleanup's disconnect.
      const subToClose = subRef.current;
      const cfToClose = cfRef.current;
      subRef.current = null;
      cfRef.current = null;

      // Clear the viewer flag so the backend treats this thread as unobserved
      // once the WebSocket is torn down.  Prevents the full ACK retry loop
      // from firing on stale flags during reconnection gaps (re-explore,
      // refresh, navigation).  Fire-and-forget — non-fatal if it fails.
      clearThreadViewer(threadId);

      // Capture and clear in-flight ACK promises.  We drain them before
      // actually disconnecting so that a `sub.publish()` started inside
      // the publication handler (which may have triggered isDone→true via
      // refresh()) gets a chance to complete over the still-open WebSocket.
      // Using Promise.allSettled ensures rejections don't block the drain.
      const pending = [...pendingAckPromsRef.current];
      pendingAckPromsRef.current.clear();
      confirmedAckKeysRef.current.clear();

      Promise.allSettled(pending).then(() => {
        subToClose?.unsubscribe();
        cfToClose?.disconnect();
      });
    };
  }, [sseInfo, done]);
}
