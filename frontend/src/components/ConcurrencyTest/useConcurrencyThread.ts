/**
 * useConcurrencyThread — lightweight per-thread SSE + LLM subscriber for
 * the concurrency test grid.
 *
 * Connects both Centrifugo tiers for a single thread and invokes onUpdate
 * with incremental state patches whenever relevant events arrive.
 * Tracks ACK metrics (sent / confirmed) without relying on the shared
 * useCentrifugoSse hook.
 */

import { useEffect, useRef, useState } from 'react';
import { Centrifuge, Subscription } from 'centrifuge';
import type { SseInfo, SseEvent } from '../../types';
import { isWorkActive, isWorkTerminal, type TerminalQueryStatus, type WorkStatusValue } from '../../constants/lifecycleStatus';
import type { ThreadRowUpdate } from './types';
import { createSseClientBundle } from '../../api/centrifugoSseClient';
import { createLlmClientBundle } from '../../api/centrifugoLlmClient';
import { getTasks } from '../../api/threads';
import { useLatestRef } from '../../hooks/refUtils';

interface Options {
  threadId: string;
  sseInfo: SseInfo | null;
  llmInfo: SseInfo | null;
  submitTime: number;
  done: boolean;
  onUpdate: (threadId: string, update: ThreadRowUpdate) => void;
}

interface ConcurrencyThreadResult {
  /** Accumulated raw token text — updated synchronously on each token, no re-render. */
  streamTextRef: React.MutableRefObject<string>;
}

export function useConcurrencyThread({
  threadId,
  sseInfo,
  llmInfo,
  submitTime,
  done,
  onUpdate,
}: Options): ConcurrencyThreadResult {
  const onUpdateRef = useLatestRef(onUpdate);

  const acksSentRef = useRef(0);
  const acksConfirmedRef = useRef(0);
  // Keys for which we have sent an RPC in this session (dedup across history replays).
  const sentAckKeysRef = useRef<Set<string>>(new Set());
  // Keys for which we have already counted an ack_confirmed (dedup replayed confirmations).
  const countedConfirmedKeysRef = useRef<Set<string>>(new Set());
  const confirmedKeysRef = useRef<Set<string>>(new Set());
  // Drain mechanism: defer terminal status until all in-flight ACKs are confirmed.
  const wantsCloseRef = useRef(false);
  const terminalStatusRef = useRef<TerminalQueryStatus | null>(null);
  const tokensRef = useRef(0);
  const maxSeqRef = useRef(0);
  const streamStartRef = useRef<number | null>(null);
  // Accumulated raw token text for the streaming display (no re-render trigger).
  const streamTextRef = useRef('');
  // Pending token metric update flushed at 300ms interval.
  const pendingTokenUpdateRef = useRef<ThreadRowUpdate | null>(null);
  // Gate: connect to LLM MQ only after the backend stream_start handshake.
  const [llmEnabled, setLlmEnabled] = useState(false);

  // ── 300ms flush interval for token metric updates ────────────────────────
  // Batches tokensReceived / maxSeq / streamStart updates so the grid table
  // re-renders at most once per 300ms instead of on every incoming token.
  useEffect(() => {
    const tid = setInterval(() => {
      if (pendingTokenUpdateRef.current !== null) {
        onUpdateRef.current(threadId, pendingTokenUpdateRef.current);
        pendingTokenUpdateRef.current = null;
      }
    }, 300);
    return () => clearInterval(tid);
  }, [threadId]);

  // ── SSE lifecycle subscription ────────────────────────────────────────────
  // Receives node/task/thread lifecycle events → updates grid row status and
  // ACK metrics.  Sends ACK RPCs back to the backend for all non-ack events.
  const sseCfRef = useRef<Centrifuge | null>(null);
  const sseSubRef = useRef<Subscription | null>(null);

  useEffect(() => {
    if (!sseInfo || done) return;
    let cancelled = false;
    // Declared in outer scope so both the async Promise callback and the
    // cleanup return function can access and clear it via closure.
    let drainTimeoutId: ReturnType<typeof setTimeout> | null = null;
    // Guard: fetch backend state at most once per terminal event.
    let reconcileInFlight = false;

    Promise.resolve().then(() => {
      if (cancelled) return;

      const { cf, sub } = createSseClientBundle(sseInfo);

      sseCfRef.current = cf;
      sseSubRef.current = sub;

      // Drain check: only set terminal status after all sent ACKs are confirmed.
      // The 'done' event arrives before ack_confirmed events for the last few events.
      // If we set status:'completed' immediately, React re-renders with done=true and
      // the SSE useEffect cleanup disconnects before those confirmations arrive.
      // Timeout fallback: if a single ack_confirmed is never delivered (RPC loss,
      // Centrifugo history gap), the drain would block forever.  After 5 s we
      // force-complete so the thread row reaches its terminal state.
      // drainTimeoutId is declared in the outer useEffect scope so cleanup can clear it.
      function checkDrain() {
        if (!wantsCloseRef.current || terminalStatusRef.current === null) return;
        if (sentAckKeysRef.current.size <= countedConfirmedKeysRef.current.size) {
          if (drainTimeoutId !== null) { clearTimeout(drainTimeoutId); drainTimeoutId = null; }
          onUpdateRef.current(threadId, { status: terminalStatusRef.current });
          return;
        }
        // Not all confirmed yet — fetch actual task state from backend once, then complete.
        // This gives the UI the real final state rather than waiting up to 5 s for
        // ack_confirmed events that may never arrive (RPC loss / history gap).
        if (!reconcileInFlight) {
          reconcileInFlight = true;
          // Keep a last-resort timeout in case the fetch itself also fails.
          if (drainTimeoutId === null) {
            drainTimeoutId = setTimeout(() => {
              drainTimeoutId = null;
              if (wantsCloseRef.current && terminalStatusRef.current !== null) {
                onUpdateRef.current(threadId, { status: terminalStatusRef.current });
              }
            }, 5_000);
          }
          getTasks(threadId)
            .then((tasks) => {
              if (cancelled) return;
              const streamTask = tasks.find((t) => t.task_name === 'stream_conclusion');
              if (streamTask?.status) {
                onUpdateRef.current(threadId, { streamTaskStatus: streamTask.status as WorkStatusValue });
              }
              if (drainTimeoutId !== null) { clearTimeout(drainTimeoutId); drainTimeoutId = null; }
              if (wantsCloseRef.current && terminalStatusRef.current !== null) {
                onUpdateRef.current(threadId, { status: terminalStatusRef.current });
              }
            })
            .catch(() => {
              // Fetch failed — 5 s fallback timer already armed will complete the drain.
            });
        }
      }

      sub.on('publication', (ctx) => {
        const ev = ctx.data as SseEvent;

        // ack_confirmed is no longer published as a channel event — confirmation
        // is signalled by sub.publish() promise resolution.  Guard to silently
        // ignore stale ack_confirmed events that may exist in Centrifugo history.
        if (ev.event === 'ack_confirmed') {
          if (ev.ack_key) confirmedKeysRef.current.add(ev.ack_key);
          checkDrain();
          return;
        }

        // ── Map SSE lifecycle events → grid row updates ──────────────────
        // stream_start: backend confirmed it is about to stream — open the LLM
        // MQ channel.  Event is still forwarded to the ACK section below.
        if (ev.event === 'stream_start') {
          setLlmEnabled(true);
        }

        // 'done' is the thread-level terminal event emitted by complete_thread().
        // It carries { status: 'completed' } and is the primary completion
        // signal when viewers_present=False (no stream_end from LLM channel).
        // Falls through to the ACK section below — do NOT early return here.
        // For terminal events, status is NOT set directly. We flag wantsClose
        // and let checkDrain() set the terminal status only after all in-flight
        // ACK confirmations have arrived. This prevents the SSE connection from
        // being torn down before ack_confirmed events for the final burst reach us.
        // NOTE: do NOT call checkDrain() here — the terminal event's own ACK has
        // not been registered in sentAckKeysRef yet. Calling checkDrain() at this
        // point would see sentSize == confirmedSize (equal) and immediately trigger
        // done=true, tearing down the connection before the terminal event's ACK
        // publish completes (causing one perpetually missing ACK). checkDrain() is
        // called at the bottom of the handler (after ACK registration) and also in
        // the early-return paths below to cover retry and history-replay cases.
        if (ev.event === 'done') {
          wantsCloseRef.current = true;
          terminalStatusRef.current = 'completed';
        } else if (ev.event === 'thread_failed') {
          wantsCloseRef.current = true;
          terminalStatusRef.current = 'failed';
        } else if (ev.event === 'thread_status') {
          const s = ev.status as string | undefined;
          if (s === 'cancelled') {
            wantsCloseRef.current = true;
            terminalStatusRef.current = 'cancelled';
          }
        } else if (ev.event === 'node_status' || ev.event === 'task_status') {
          // Infer thread-level 'running' from the first active node/task event,
          // since the backend emits no explicit thread_status:running SSE event.
          if ((ev.status as string | undefined) === 'running') {
            onUpdateRef.current(threadId, { status: 'running' });
          }
          if (ev.event === 'node_status' && ev.node_name === 'conclusion_node' && ev.status === 'running') {
            const latency = Date.now() - submitTime;
            onUpdateRef.current(threadId, { latencyToConclusion: latency });
          }
          if (ev.event === 'task_status' && ev.view_type === 'Streaming') {
            const s = ev.status as string | undefined;
            if (s && (isWorkActive(s) || isWorkTerminal(s))) {
              onUpdateRef.current(threadId, { streamTaskStatus: s as import('./types').ThreadRow['streamTaskStatus'] });
            }
          }
        }

        // ── Send ACK for all non-ack events ──────────────────────────────
        const ackKey: string =
          (ev.ack_key as string | undefined) ??
          (ev.task_id
            ? `task:${ev.task_id}:${ev.status ?? ev.event}`
            : ev.node_id
            ? `node:${ev.node_id}:${ev.status ?? ev.event}`
            : `thread:${ev.event}:${ev.status ?? ''}`);

        // Deduplicate sending: history can replay the same event multiple times
        // (backend retries with the same ack_key). Only send one publish per key.
        // Call checkDrain() before returning so that terminal events which arrive
        // as retries or history-replays (already in sent/confirmed sets) still
        // trigger the drain gate correctly.
        if (confirmedKeysRef.current.has(ackKey)) {
          if (wantsCloseRef.current) checkDrain();
          return;
        }
        if (sentAckKeysRef.current.has(ackKey)) {
          if (wantsCloseRef.current) checkDrain();
          return;
        }
        sentAckKeysRef.current.add(ackKey);

        acksSentRef.current += 1;
        onUpdateRef.current(threadId, { acksSent: acksSentRef.current });

        sub.publish({
          event: 'ack',
          scope: ev.task_id ? 'task' : ev.node_id ? 'node' : 'thread',
          ack_key: ackKey,
          thread_id: threadId,
        }).then(() => {
          // sub.publish() resolves when Centrifugo's publish proxy returns 200,
          // meaning the backend LPUSH already succeeded — this IS the confirmation.
          confirmedKeysRef.current.add(ackKey);
          if (!countedConfirmedKeysRef.current.has(ackKey)) {
            countedConfirmedKeysRef.current.add(ackKey);
            acksConfirmedRef.current += 1;
            onUpdateRef.current(threadId, { acksConfirmed: acksConfirmedRef.current });
          }
          checkDrain();
        }).catch((err) => {
          // code 11 = connection closed — expected on cleanup, not actionable.
          if (err && typeof err === 'object' && (err as { code?: number }).code === 11) return;
          // On publish failure the backend never received the ACK.  Remove from
          // sentAckKeys so the drain gate is not permanently blocked.
          // NOTE: do NOT decrement acksSentRef — it is a monotonic send counter.
          sentAckKeysRef.current.delete(ackKey);
          checkDrain();
        });
        // Check drain after ACK is registered: handles both the normal case
        // (terminal event's ACK now in sentAckKeysRef so drain waits for it)
        // and the fast path where all ACKs are already confirmed.
        checkDrain();
      });

      sub.subscribe();
      cf.connect();
    });

    return () => {
      cancelled = true;
      if (drainTimeoutId !== null) { clearTimeout(drainTimeoutId); drainTimeoutId = null; }
      sseSubRef.current?.unsubscribe();
      sseCfRef.current?.disconnect();
      sseCfRef.current = null;
      sseSubRef.current = null;
      confirmedKeysRef.current.clear();
      sentAckKeysRef.current.clear();
      countedConfirmedKeysRef.current.clear();
      wantsCloseRef.current = false;
      terminalStatusRef.current = null;
    };
  }, [sseInfo, done, threadId, submitTime]);

  // ── LLM token subscription ────────────────────────────────────────────────
  // Receives token / stream_end events → updates TPS and token count metrics.
  // Separate from the SSE tier: no ACK sending, no lifecycle handling here.
  // NOT gated on `done`: the drain mechanism can set done=true before this
  // effect runs (when SSE history replays quickly). The subscription is kept
  // alive until component unmount (leaving the thread), not torn down on stream_end.
  // Gated on `llmEnabled`: connects only after the backend stream_start
  // handshake so the MQ subscription is ready before the first token arrives.
  const llmCfRef = useRef<Centrifuge | null>(null);
  const llmSubRef = useRef<Subscription | null>(null);

  useEffect(() => {
    if (!llmInfo || !llmEnabled) return;
    let cancelled = false;

    Promise.resolve().then(() => {
      if (cancelled) return;

      const { cf, sub } = createLlmClientBundle(llmInfo);

      llmCfRef.current = cf;
      llmSubRef.current = sub;

      sub.on('subscribed', () => {
        onUpdateRef.current(threadId, { llmMqConnected: true });
      });
      sub.on('unsubscribed', () => {
        onUpdateRef.current(threadId, { llmMqConnected: false });
      });

      sub.on('publication', (ctx) => {
        const ev = ctx.data as Record<string, unknown>;

        if (ev['event'] === 'token') {
          const now = Date.now();
          const token = typeof ev['token'] === 'string' ? (ev['token'] as string) : '';
          streamTextRef.current += token;
          if (streamStartRef.current === null) {
            streamStartRef.current = now;
            // streamStart is a one-time event — update immediately.
            onUpdateRef.current(threadId, { streamStart: now });
          }
          tokensRef.current += 1;
          const seq = typeof ev['seq'] === 'number' ? (ev['seq'] as number) : 0;
          if (seq > maxSeqRef.current) maxSeqRef.current = seq;
          // Batch token count updates — flushed by the 300ms interval.
          pendingTokenUpdateRef.current = {
            tokensReceived: tokensRef.current,
            maxSeq: maxSeqRef.current,
          };
        }

        if (ev['event'] === 'stream_end') {
          const now = Date.now();
          const totalSeq = typeof ev['total_seq'] === 'number' ? (ev['total_seq'] as number) : null;
          const elapsed = streamStartRef.current !== null ? (now - streamStartRef.current) / 1000 : 1;
          const tps = elapsed > 0 ? tokensRef.current / elapsed : 0;
          // Do NOT set status: 'completed' here — thread completion is driven by the
          // SSE 'done' event only. streamTaskStatus: 'completed' is safe.
          onUpdateRef.current(threadId, {
            streamEnd: now,
            totalSeq,
            currentTps: Math.round(tps * 10) / 10,
            streamTaskStatus: 'completed',
          });
        }
      });

      sub.subscribe();
      cf.connect();
    });

    return () => {
      cancelled = true;
      llmSubRef.current?.unsubscribe();
      llmCfRef.current?.disconnect();
      llmCfRef.current = null;
      llmSubRef.current = null;
    };
  // Only depend on llmInfo, threadId, and llmEnabled — NOT on `done`. The SSE drain
  // can resolve before this effect runs (history-replay fast path). Disconnection
  // happens on component unmount (leaving the thread) only.
  }, [llmInfo, threadId, llmEnabled]);

  return { streamTextRef };
}
