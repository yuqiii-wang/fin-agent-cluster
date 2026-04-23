import { useCallback, useEffect, useRef, useState } from "react";
import type React from "react";
import type { ChatMessage, ThreadSummary } from "../types";
import { cancelQuery, createAckHandlers, fetchHistory, fetchStreamingStatus, openStream, submitQuery } from "../api";
import { buildSseHandlers } from "./sseHandlers";

const PERF_TEST_TRIGGER = "DO STREAMING PERFORMANCE TEST NOW";

export interface UseStreamSessionReturn {
  messages: ChatMessage[];
  loading: boolean;
  tokenStreams: Record<number, string>;
  taskProviders: Record<number, string>;
  /**
   * Counter used as the `key` prop for `StreamingPerfTestPanel`.
   * 0 = panel hidden; > 0 = panel visible (incremented each time a new test starts).
   */
  perfTestKey: number;
  /** Show a new (fresh) perf-test panel. Increments perfTestKey. */
  startPerfTest: () => void;
  /** Hide the perf-test panel. Resets perfTestKey to 0. */
  exitPerfTest: () => void;
  /** Force the streaming_perf_test assistant message to completed + show node as completed. */
  forcePerfTestComplete: () => void;
  recoverThread: (thread: ThreadSummary) => void;
  handleSubmit: (query: string) => Promise<void>;
  handleCancel: () => Promise<void>;
}

/**
 * Manages all SSE stream state for the main chat session.
 * Encapsulates messages, loading, token streams, and SSE lifecycle.
 */
export function useStreamSession(
  userToken: string | null,
  setHistoryItems: React.Dispatch<React.SetStateAction<ThreadSummary[]>>,
): UseStreamSessionReturn {
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [loading, setLoading] = useState(false);
  const [tokenStreams, setTokenStreams] = useState<Record<number, string>>({});
  const [taskProviders, setTaskProviders] = useState<Record<number, string>>({});
  const [perfTestKey, setPerfTestKey] = useState(0);

  const threadToMsgId = useRef<Map<string, string>>(new Map());
  const cleanupSse = useRef<(() => void) | null>(null);
  const activeThreadId = useRef<string | null>(null);
  /** Timestamp (Date.now()) of the last SSE token event received. Reset to Date.now() on session start. */
  const lastTokenAtRef = useRef<number>(0);

  // ── Token accumulation buffers (never trigger React renders directly) ────
  /** msgId → text delta accumulated since last 100 ms flush. */
  const msgTextBufferRef = useRef<Record<string, string>>({});
  /** taskId → token delta accumulated since last 100 ms flush. */
  const taskTokenBufferRef = useRef<Record<number, string>>({});

  /** Push a token delta for a task into the buffer — zero React overhead. */
  const pushTokenStream = useCallback((taskId: number, token: string) => {
    taskTokenBufferRef.current[taskId] = (taskTokenBufferRef.current[taskId] ?? "") + token;
  }, []);

  /** Flush both token buffers to React state at most once per 100 ms. */
  useEffect(() => {
    const id = setInterval(() => {
      const msgFlush = msgTextBufferRef.current;
      const taskFlush = taskTokenBufferRef.current;
      const hasMsgUpdates = Object.keys(msgFlush).length > 0;
      const hasTaskUpdates = Object.keys(taskFlush).length > 0;
      if (!hasMsgUpdates && !hasTaskUpdates) return;
      if (hasMsgUpdates) {
        msgTextBufferRef.current = {};
        setMessages((prev) =>
          prev.map((m) => {
            const pending = msgFlush[m.id];
            return pending ? { ...m, text: m.text + pending, streamingCursor: true } : m;
          })
        );
      }
      if (hasTaskUpdates) {
        taskTokenBufferRef.current = {};
        setTokenStreams((prev) => {
          const next = { ...prev };
          for (const [key, text] of Object.entries(taskFlush)) {
            const taskId = Number(key);
            next[taskId] = (next[taskId] ?? "") + text;
          }
          return next;
        });
      }
    }, 100);
    return () => clearInterval(id);
  }, []);
  // ─────────────────────────────────────────────────────────────────────────

  const updateMessage = useCallback((msgId: string, patch: Partial<ChatMessage>) => {
    setMessages((prev) => prev.map((m) => (m.id === msgId ? { ...m, ...patch } : m)));
  }, []);

  /** Push message text delta into the buffer — flushed to React state every 100 ms. */
  const appendMessageText = useCallback((msgId: string, token: string) => {
    msgTextBufferRef.current[msgId] = (msgTextBufferRef.current[msgId] ?? "") + token;
  }, []);

  // ── 5-second stall detection ──────────────────────────────────────────────
  // When loading is true and no token has been received for ≥ 5 seconds, poll
  // the backend streaming-status endpoint to check whether the task is still
  // alive.  If the backend task is gone but the DB still shows 'running' the
  // session is orphaned and should be marked failed immediately.
  useEffect(() => {
    if (!loading) {
      lastTokenAtRef.current = Date.now();
      return;
    }
    const tid = activeThreadId.current;
    if (!tid) return;
    let lastStatusCheckAt = 0;
    const intervalId = setInterval(async () => {
      const elapsed = Date.now() - lastTokenAtRef.current;
      if (elapsed < 5_000) return;
      if (Date.now() - lastStatusCheckAt < 5_000) return;
      lastStatusCheckAt = Date.now();
      try {
        const status = await fetchStreamingStatus(tid);
        console.debug(
          "[useStreamSession] stream_stall tid=%s elapsed=%dms query_status=%s is_active=%s running_tasks=%d last_token_ms_ago=%s",
          tid, elapsed, status.query_status, status.is_active, status.running_tasks.length, status.last_token_ms_ago,
        );
        // Backend task gone without emitting done → orphan; surface as failure.
        if (!status.is_active && status.query_status === "running") {
          const msgId = threadToMsgId.current.get(tid);
          if (msgId) updateMessage(msgId, { status: "failed" as ChatMessage["status"], streamingCursor: false });
          activeThreadId.current = null;
          setLoading(false);
        }
      } catch (err) {
        console.warn("[useStreamSession] stream_stall_check failed tid=%s", tid, err);
      }
    }, 1_000);
    return () => clearInterval(intervalId);
  }, [loading, updateMessage]);
  // ─────────────────────────────────────────────────────────────────────────

  const recoverThread = useCallback((thread: ThreadSummary) => {
    cleanupSse.current?.();
    const asstMsgId = crypto.randomUUID();
    threadToMsgId.current.set(thread.thread_id, asstMsgId);
    activeThreadId.current = thread.thread_id;

    setTokenStreams({});
    setTaskProviders({});
    setMessages([
      { id: crypto.randomUUID(), role: "user", text: thread.query },
      {
        id: asstMsgId,
        role: "assistant",
        text: thread.answer ?? "",
        status: thread.status as ChatMessage["status"],
        thread_id: thread.thread_id,
        nodes: [],
      },
    ]);

    if (thread.status === "running" || thread.status === "pending" || thread.status === "received") {
      setLoading(true);
      lastTokenAtRef.current = Date.now();
      msgTextBufferRef.current = {};
      taskTokenBufferRef.current = {};
      const closeRef = { current: (() => {}) as () => void };
      const baseHandlers = buildSseHandlers({
        asstMsgId,
        threadId: thread.thread_id,
        setMessages,
        pushTokenStream,
        setTaskProviders,
        appendMessageText,
        updateMessage,
        onDone: (status) => {
          updateMessage(asstMsgId, { status: status as ChatMessage["status"], streamingCursor: false });
          activeThreadId.current = null;
          setLoading(false);
          closeRef.current();
          if (userToken) fetchHistory(userToken).then(setHistoryItems).catch(console.error);
        },
        onClose: () => {
          updateMessage(asstMsgId, { status: "failed" as ChatMessage["status"], streamingCursor: false });
          activeThreadId.current = null;
          setLoading(false);
        },
        onConnectionFailed: (message) => {
          updateMessage(asstMsgId, { text: message, status: "failed" as ChatMessage["status"], streamingCursor: false });
          activeThreadId.current = null;
          setLoading(false);
        },
      });
      const close = openStream(thread.thread_id, {
        ...baseHandlers,
        // Intercept token events to update stall-detection timer.
        onToken: (data) => {
          lastTokenAtRef.current = Date.now();
          baseHandlers.onToken?.(data);
        },
        // Handle query_received if recovering a thread that hasn't been ACKed yet.
        ...(userToken ? createAckHandlers(thread.thread_id, userToken, "recoverThread") : {}),
      });
      closeRef.current = close;
      cleanupSse.current = close;
    }
  }, [appendMessageText, updateMessage, userToken, setHistoryItems]);

  const handleSubmit = useCallback(async (query: string) => {
    if (!userToken) return;
    cleanupSse.current?.();
    setTokenStreams({});
    setTaskProviders({});
    msgTextBufferRef.current = {};
    taskTokenBufferRef.current = {};

    const userMsgId = crypto.randomUUID();
    const asstMsgId = crypto.randomUUID();

    // ── Performance test fast-path ──
    if (query.trim().startsWith(PERF_TEST_TRIGGER)) {
      // Do NOT submit any backend query here. The panel's useSessionManager
      // submits all streams (Stream #1 … #N) with the correct config params.
      setMessages([
        { id: userMsgId, role: "user", text: query },
        {
          id: asstMsgId,
          role: "assistant",
          text: "Streaming Performance test grid",
          status: "running",
          isPerfTest: true,
          nodes: [],
        },
      ]);
      setPerfTestKey((k) => k + 1);
      return;
    }

    // ── Normal submit ──
    setMessages((prev) => [
      ...prev,
      { id: userMsgId, role: "user", text: query },
      { id: asstMsgId, role: "assistant", text: "", status: "running", nodes: [] },
    ]);
    setLoading(true);
    lastTokenAtRef.current = Date.now();

    try {
      const res = await submitQuery(query, userToken);
      const threadId = res.thread_id;

      // NACK: duplicate submission within dedup window — attach to the existing stream.
      if (res.status === "cancelled") {
        console.warn("[useStreamSession] duplicate query NACK, reattaching to thread_id=%s", threadId);
        threadToMsgId.current.set(threadId, asstMsgId);
        activeThreadId.current = threadId;
        updateMessage(asstMsgId, { thread_id: threadId });
        // Open SSE and let the existing graph events flow through.
        const closeRef = { current: (() => {}) as () => void };
        const nackBase = buildSseHandlers({
          asstMsgId,
          threadId,
          setMessages,
          pushTokenStream,
          setTaskProviders,
          appendMessageText,
          updateMessage,
          withReport: true,
          onDone: (status) => {
            if (status === "cancelled") {
              updateMessage(asstMsgId, { text: "Query cancelled by user.", status: "cancelled" as ChatMessage["status"], streamingCursor: false });
            } else {
              updateMessage(asstMsgId, { status: status as ChatMessage["status"], streamingCursor: false });
            }
            activeThreadId.current = null;
            closeRef.current();
            setLoading(false);
            if (userToken) fetchHistory(userToken).then(setHistoryItems).catch(console.error);
          },
          onClose: () => {
            updateMessage(asstMsgId, { status: "failed" as ChatMessage["status"], streamingCursor: false });
            activeThreadId.current = null;
            setLoading(false);
          },
          onConnectionFailed: (message) => {
            updateMessage(asstMsgId, { text: message, status: "failed" as ChatMessage["status"], streamingCursor: false });
            activeThreadId.current = null;
            setLoading(false);
          },
        });
        const close = openStream(threadId, {
          ...nackBase,
          onToken: (data) => {
            lastTokenAtRef.current = Date.now();
            nackBase.onToken?.(data);
          },
        });
        closeRef.current = close;
        cleanupSse.current = close;
        return;
      }

      threadToMsgId.current.set(threadId, asstMsgId);
      activeThreadId.current = threadId;
      updateMessage(asstMsgId, { thread_id: threadId });

      const closeRef = { current: (() => {}) as () => void };
      const baseHandlers = buildSseHandlers({
        asstMsgId,
        threadId,
        setMessages,
        pushTokenStream,
        setTaskProviders,
        appendMessageText,
        updateMessage,
        withReport: true,
        onDone: (status) => {
          if (status === "cancelled") {
            updateMessage(asstMsgId, { text: "Query cancelled by user.", status: "cancelled" as ChatMessage["status"], streamingCursor: false });
          } else {
            updateMessage(asstMsgId, { status: status as ChatMessage["status"], streamingCursor: false });
          }
          activeThreadId.current = null;
          closeRef.current();
          setLoading(false);
          if (userToken) fetchHistory(userToken).then(setHistoryItems).catch(console.error);
        },
        onClose: () => {
          updateMessage(asstMsgId, { status: "failed" as ChatMessage["status"], streamingCursor: false });
          activeThreadId.current = null;
          setLoading(false);
        },
        onConnectionFailed: (message) => {
          updateMessage(asstMsgId, { text: message, status: "failed" as ChatMessage["status"], streamingCursor: false });
          activeThreadId.current = null;
          setLoading(false);
        },
      });
      const close = openStream(threadId, {
        ...baseHandlers,
        // Intercept token events to update stall-detection timer.
        onToken: (data) => {
          lastTokenAtRef.current = Date.now();
          baseHandlers.onToken?.(data);
        },
        ...createAckHandlers(threadId, userToken, "useStreamSession"),
      });
      closeRef.current = close;
      cleanupSse.current = close;
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : String(err);
      updateMessage(asstMsgId, { text: `Error: ${msg}`, status: "failed" });
      setLoading(false);
    }
  }, [updateMessage, appendMessageText, pushTokenStream, userToken, setHistoryItems]);

  const handleCancel = useCallback(async () => {
    const threadId = activeThreadId.current;
    if (!threadId) return;
    try {
      await cancelQuery(threadId);
    } catch {
      cleanupSse.current?.();
      setLoading(false);
    }
  }, []);

  const forcePerfTestComplete = useCallback(() => {
    setMessages((prev) =>
      prev.map((m) =>
        m.isPerfTest
          ? {
              ...m,
              status: "completed",
              nodes: [{ node_name: "perf_test_streamer", status: "completed", tasks: [] }],
            }
          : m
      )
    );
  }, []);

  return {
    messages,
    loading,
    tokenStreams,
    taskProviders,
    perfTestKey,
    startPerfTest: useCallback(() => setPerfTestKey((k) => k + 1), []),
    exitPerfTest: useCallback(() => setPerfTestKey(0), []),
    forcePerfTestComplete,
    recoverThread,
    handleSubmit,
    handleCancel,
  };
}
