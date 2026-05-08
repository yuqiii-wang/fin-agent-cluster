/**
 * useTaskStream — on-demand Centrifugo subscription for a single thread's
 * perf-token stream.
 *
 * Subscribes to thread:{threadId} when enabled=true and tears down when
 * enabled becomes false or the component unmounts.  Accumulates token_batch
 * events with 100ms flush batching to keep React re-renders ≤ 10/s.
 *
 * Reads userToken from localStorage via getStoredToken() — no prop threading needed.
 *
 * Phase transitions:
 *   idle → connecting → streaming → done | error
 *
 * Used by TaskStreamViewer (OutputViewer on-demand streaming).
 */

import { useCallback, useEffect, useRef, useState } from "react";
import { openTokenStream } from "../../../api/stream";
import { getStoredToken } from "../../../api";

export type TaskStreamPhase = "idle" | "connecting" | "streaming" | "done" | "error";

export interface UseTaskStreamReturn {
  /** Latest accumulated stream text (SET semantics — replaces on each batch). */
  streamText: string;
  /** Total tokens received so far. */
  tokenCount: number;
  /** Connection + streaming lifecycle phase. */
  phase: TaskStreamPhase;
}

/**
 * Manages an on-demand Centrifugo subscription for a single thread's
 * token_batch stream.  Subscribes when enabled=true, unsubscribes when
 * enabled becomes false or the component unmounts.
 *
 * @param threadId  LangGraph thread UUID (task.thread_id).
 * @param enabled   Open subscription when true; tear down when false.
 */
export function useTaskStream(
  threadId: string | null | undefined,
  enabled: boolean,
): UseTaskStreamReturn {
  const [streamText, setStreamText] = useState("");
  const [tokenCount, setTokenCount] = useState(0);
  const [phase, setPhase] = useState<TaskStreamPhase>("idle");

  const cleanupRef = useRef<(() => void) | null>(null);
  const flushRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const totalRef = useRef(0);
  // Pending token data — SET semantics for text (latest batch wins), ADD for count delta.
  const pendingTextRef = useRef<string | null>(null);
  const pendingCountRef = useRef(0);
  // Accumulated text for single-token mode (opt-in streaming).
  const accTextRef = useRef("");
  // Ref-tracked phase so Centrifugo event callbacks see current value without
  // stale closure issues.
  const phaseRef = useRef<TaskStreamPhase>("idle");

  const teardown = useCallback(() => {
    if (flushRef.current != null) {
      clearInterval(flushRef.current);
      flushRef.current = null;
      // Flush any buffered tokens that haven't been committed to state yet.
      const txt = pendingTextRef.current;
      const cnt = pendingCountRef.current;
      pendingTextRef.current = null;
      pendingCountRef.current = 0;
      if (txt !== null) setStreamText(txt);
      if (cnt > 0) setTokenCount((prev) => prev + cnt);
    }
    cleanupRef.current?.();
    cleanupRef.current = null;
  }, []);

  useEffect(() => {
    if (!enabled || !threadId) {
      teardown();
      // If we were streaming, transition to "done" and preserve accumulated text.
      // Only reset to idle if we never reached streaming (connecting/error/idle).
      if (phaseRef.current === "streaming") {
        phaseRef.current = "done";
        setPhase("done");
      } else {
        phaseRef.current = "idle";
        setPhase("idle");
        setStreamText("");
        setTokenCount(0);
      }
      return;
    }

    const userToken = getStoredToken();
    if (!userToken) {
      phaseRef.current = "error";
      setPhase("error");
      return;
    }

    // Reset for fresh subscription.
    totalRef.current = 0;
    accTextRef.current = "";
    pendingTextRef.current = null;
    pendingCountRef.current = 0;
    setStreamText("");
    setTokenCount(0);
    phaseRef.current = "connecting";
    setPhase("connecting");

    // 100ms flush interval — batches React state updates to ≤10 renders/s.
    flushRef.current = setInterval(() => {
      const txt = pendingTextRef.current;
      const cnt = pendingCountRef.current;
      if (txt === null && cnt === 0) return;
      pendingTextRef.current = null;
      pendingCountRef.current = 0;
      if (txt !== null) setStreamText(txt);
      if (cnt > 0) setTokenCount((prev) => prev + cnt);
    }, 100);

    const closeToken = openTokenStream(threadId, userToken, {
      onToken: (data) => {
        const d = data as { data?: string };
        const tok = d.data ?? "";
        if (!tok) return;
        totalRef.current += 1;
        accTextRef.current += tok;
        pendingTextRef.current = accTextRef.current;
        pendingCountRef.current += 1;
        if (phaseRef.current !== "streaming") {
          phaseRef.current = "streaming";
          setPhase("streaming");
        }
      },
      onTokenBatch: (data) => {
        const d = data as { count?: number; recent_tokens?: string[] };
        const recentTokens = d.recent_tokens ?? [];
        const count = d.count ?? recentTokens.length;
        if (count === 0) return;
        totalRef.current += count;
        // Mirror tokenHandler.ts stream_text formula.
        const text =
          (totalRef.current > recentTokens.length ? "…\n" : "") +
          recentTokens.join("\n");
        pendingTextRef.current = text;
        pendingCountRef.current += count;
        if (phaseRef.current !== "streaming") {
          phaseRef.current = "streaming";
          setPhase("streaming");
        }
      },
    });
    cleanupRef.current = closeToken;
    return teardown;
  }, [enabled, threadId, teardown]);

  return { streamText, tokenCount, phase };
}
