/**
 * useCentrifugoSse — subscribe to the SSE lifecycle Centrifugo tier.
 *
 * Connects to centrifugo-sse-{shard} using the bootstrap info from the
 * submit_query response.  Fires onEvent on every publication.  Sends an
 * RPC ACK back to the backend for events that require acknowledgement.
 */

import { useEffect, useRef } from 'react';
import { Centrifuge, Subscription } from 'centrifuge';
import type { SseEvent, SseInfo } from '../types';

interface Options {
  sseInfo: SseInfo | null;
  onEvent: (ev: SseEvent) => void;
  /** Set to true once the thread reaches a terminal state. */
  done: boolean;
}

export function useCentrifugoSse({ sseInfo, onEvent, done }: Options): void {
  const cfRef = useRef<Centrifuge | null>(null);
  const subRef = useRef<Subscription | null>(null);
  const onEventRef = useRef(onEvent);
  onEventRef.current = onEvent;
  // Tracks ack_keys for which the backend has already confirmed receipt.
  // Once an ack_key is confirmed we must not send another ACK for retried
  // copies of the same event, since the backend has already stopped listening.
  const confirmedAckKeysRef = useRef<Set<string>>(new Set());

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

      const cf = new Centrifuge(sseInfo.ws_url, {
        token: sseInfo.connection_token,
      });

      const sub = cf.newSubscription(sseInfo.channel, {
        token: sseInfo.subscription_token,
        // Request history recovery from the beginning of the current epoch so
        // messages published before this subscription connected are replayed.
        since: { offset: 0, epoch: '' },
      });

      // Store refs before connecting so cleanup can reach them if it fires
      // after this microtask but before the connection is torn down.
      cfRef.current = cf;
      subRef.current = sub;

      sub.on('publication', (ctx) => {
        const ev = ctx.data as SseEvent;
        onEventRef.current(ev);

        // When the backend confirms an ACK round-trip, record the ack_key so
        // we do not re-ACK retried copies of the same event.
        if (ev.event === 'ack_confirmed') {
          if (ev.ack_key) {
            confirmedAckKeysRef.current.add(ev.ack_key);
          }
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

        cf.rpc('thread_ack', {
          scope: ev.task_id ? 'task' : ev.node_id ? 'node' : 'thread',
          ack_key: ackKey,
          thread_id: tid,
        }).catch((err: unknown) => {
          // code 11 = "connection closed" — Centrifugo disconnected before the
          // RPC completed (tab close / navigation / subscription tear-down).
          // This is expected and not actionable; suppress to avoid console noise.
          if (err && typeof err === 'object' && (err as { code?: number }).code === 11) {
            return;
          }
          console.error('[sse-ack] RPC failed event=%s ack_key=%s: %o', ev.event, ackKey, err);
        });
      });

      sub.subscribe();
      cf.connect();
    });

    return () => {
      cancelled = true;
      // cfRef.current is null when the microtask was pre-empted by this
      // cleanup (StrictMode double-invoke) — safe to call on null via ?.
      subRef.current?.unsubscribe();
      cfRef.current?.disconnect();
      cfRef.current = null;
      subRef.current = null;
      confirmedAckKeysRef.current.clear();
    };
  }, [sseInfo, done]);
}
