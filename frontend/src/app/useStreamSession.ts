import { useCallback, useRef, useState } from "react";
import type React from "react";
import type { ChatMessage, ThreadSummary } from "../types";
import { cancelQuery, fetchHistory, openStream, submitQuery } from "../api";
import { buildSseHandlers } from "./sseHandlers";

const PERF_TEST_TRIGGER = "DO STREAMING PERFORMANCE TEST NOW";

export interface UseStreamSessionReturn {
  messages: ChatMessage[];
  loading: boolean;
  tokenStreams: Record<number, string>;
  taskProviders: Record<number, string>;
  perfTestThreadId: string | null;
  setPerfTestThreadId: React.Dispatch<React.SetStateAction<string | null>>;
  perfTestGridVisible: boolean;
  setPerfTestGridVisible: React.Dispatch<React.SetStateAction<boolean>>;
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
  const [perfTestThreadId, setPerfTestThreadId] = useState<string | null>(null);
  const [perfTestGridVisible, setPerfTestGridVisible] = useState(true);

  const threadToMsgId = useRef<Map<string, string>>(new Map());
  const cleanupSse = useRef<(() => void) | null>(null);
  const activeThreadId = useRef<string | null>(null);

  const updateMessage = useCallback((msgId: string, patch: Partial<ChatMessage>) => {
    setMessages((prev) => prev.map((m) => (m.id === msgId ? { ...m, ...patch } : m)));
  }, []);

  const appendMessageText = useCallback((msgId: string, token: string) => {
    setMessages((prev) => prev.map((m) => (m.id === msgId ? { ...m, text: m.text + token, streamingCursor: true } : m)));
  }, []);

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

    if (thread.status === "running" || thread.status === "pending") {
      setLoading(true);
      const closeRef = { current: (() => {}) as () => void };
      const close = openStream(thread.thread_id, buildSseHandlers({
        asstMsgId,
        threadId: thread.thread_id,
        setMessages,
        setTokenStreams,
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
      }));
      closeRef.current = close;
      cleanupSse.current = close;
    }
  }, [appendMessageText, updateMessage, userToken, setHistoryItems]);

  const handleSubmit = useCallback(async (query: string) => {
    if (!userToken) return;
    cleanupSse.current?.();
    setTokenStreams({});
    setTaskProviders({});

    const userMsgId = crypto.randomUUID();
    const asstMsgId = crypto.randomUUID();

    // ── Performance test fast-path ──
    if (query.trim() === PERF_TEST_TRIGGER) {
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
      setLoading(true);
      try {
        const res = await submitQuery(query, userToken, { perf_num_requests: 5 });
        const threadId = res.thread_id;
        updateMessage(asstMsgId, { thread_id: threadId });
        activeThreadId.current = threadId;
        threadToMsgId.current.set(threadId, asstMsgId);

        // Open SSE stream to populate TaskDrawer with real task/node data.
        // StreamingPerfTestPanel opens a second SSE connection for the grid metrics.
        const closeRef = { current: (() => {}) as () => void };
        const close = openStream(threadId, buildSseHandlers({
          asstMsgId,
          threadId,
          setMessages,
          setTokenStreams,
          setTaskProviders,
          appendMessageText,
          updateMessage,
          onDone: (status) => {
            updateMessage(asstMsgId, { status: status as ChatMessage["status"], streamingCursor: false });
            activeThreadId.current = null;
            closeRef.current();
          },
          onClose: () => {
            activeThreadId.current = null;
          },
        }));
        closeRef.current = close;
        cleanupSse.current = close;

        setLoading(false);
        setPerfTestThreadId(threadId);
        setPerfTestGridVisible(true);
      } catch (err) {
        console.error("[perf_test] submit failed:", err);
        setLoading(false);
      }
      return;
    }

    // ── Normal submit ──
    setMessages((prev) => [
      ...prev,
      { id: userMsgId, role: "user", text: query },
      { id: asstMsgId, role: "assistant", text: "", status: "running", nodes: [] },
    ]);
    setLoading(true);

    try {
      const res = await submitQuery(query, userToken);
      const threadId = res.thread_id;
      threadToMsgId.current.set(threadId, asstMsgId);
      activeThreadId.current = threadId;
      updateMessage(asstMsgId, { thread_id: threadId });

      const closeRef = { current: (() => {}) as () => void };
      const close = openStream(threadId, buildSseHandlers({
        asstMsgId,
        threadId,
        setMessages,
        setTokenStreams,
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
      }));
      closeRef.current = close;
      cleanupSse.current = close;
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : String(err);
      updateMessage(asstMsgId, { text: `Error: ${msg}`, status: "failed" });
      setLoading(false);
    }
  }, [updateMessage, appendMessageText, userToken, setHistoryItems]);

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
        m.thread_id === perfTestThreadId
          ? {
              ...m,
              status: "completed",
              nodes: [{ node_name: "perf_test_streamer", status: "completed", tasks: [] }],
            }
          : m
      )
    );
  }, [perfTestThreadId]);

  return {
    messages,
    loading,
    tokenStreams,
    taskProviders,
    perfTestThreadId,
    setPerfTestThreadId,
    perfTestGridVisible,
    setPerfTestGridVisible,
    forcePerfTestComplete,
    recoverThread,
    handleSubmit,
    handleCancel,
  };
}
