import type React from "react";
import type { ChatMessage, NodeGroup, TaskInfo } from "../types";
import { fetchReportById } from "../api";

interface SseHandlerParams {
  asstMsgId: string;
  threadId: string;
  setMessages: React.Dispatch<React.SetStateAction<ChatMessage[]>>;
  setTokenStreams: React.Dispatch<React.SetStateAction<Record<number, string>>>;
  setTaskProviders: React.Dispatch<React.SetStateAction<Record<number, string>>>;
  appendMessageText: (msgId: string, token: string) => void;
  updateMessage: (msgId: string, patch: Partial<ChatMessage>) => void;
  onDone: (status: string) => void;
  onClose: () => void;
  /** When true, fetches and attaches a StrategyReport on db_insert_report completion. */
  withReport?: boolean;
}

/**
 * Factory that builds the full set of SSE event handlers for a given assistant message.
 * Handles onStarted, onToken, onCompleted, onFailed, onCancelled, onDone, and onClose.
 */
export function buildSseHandlers({
  asstMsgId,
  threadId,
  setMessages,
  setTokenStreams,
  setTaskProviders,
  appendMessageText,
  updateMessage,
  onDone,
  onClose,
  withReport = false,
}: SseHandlerParams) {
  return {
    onStarted: (data: unknown) => {
      const { task_id, node_name, task_key, provider } = data as {
        task_id: number; node_name: string; task_key: string; provider?: string;
      };
      if (provider) setTaskProviders((prev) => ({ ...prev, [task_id]: provider }));
      const newTask: TaskInfo = {
        id: task_id,
        thread_id: threadId,
        node_execution_id: null,
        node_name,
        task_key,
        status: "running",
        input: {},
        output: {},
        created_at: new Date().toISOString(),
        updated_at: new Date().toISOString(),
      };
      setMessages((prev) =>
        prev.map((m) => {
          if (m.id !== asstMsgId) return m;
          const nodes = m.nodes ?? [];
          const existing = nodes.find((n) => n.node_name === node_name);
          if (existing) {
            return {
              ...m,
              nodes: nodes.map((n) =>
                n.node_name === node_name
                  ? { ...n, status: "running" as const, tasks: [...n.tasks, newTask] }
                  : n
              ),
            };
          }
          return { ...m, nodes: [...nodes, { node_name, status: "running" as const, tasks: [newTask] }] };
        })
      );
    },

    onToken: (data: unknown) => {
      const { task_id, task_key, data: token } = data as {
        task_id: number; task_key: string; data: string;
      };
      if (task_key === "llm_analysis") appendMessageText(asstMsgId, token);
      setTokenStreams((prev) => ({ ...prev, [task_id]: (prev[task_id] ?? "") + token }));
    },

    onCompleted: (data: unknown) => {
      const { task_id, node_name, task_key, output } = data as {
        task_id: number; node_name: string; task_key: string; output: Record<string, unknown>;
      };
      const safeOutput = output?._truncated ? undefined : output;
      setMessages((prev) =>
        prev.map((m) => {
          if (m.id !== asstMsgId || !m.nodes) return m;
          return {
            ...m,
            nodes: m.nodes.map((ng) => {
              if (ng.node_name !== node_name) return ng;
              const tasks = ng.tasks.map((t) =>
                t.id === task_id
                  ? { ...t, status: "completed" as const, output: safeOutput ?? t.output }
                  : t
              );
              const allDone = tasks.every((t) =>
                t.status === "completed" || t.status === "failed" || t.status === "cancelled"
              );
              return { ...ng, tasks, status: (allDone ? "completed" : ng.status) as NodeGroup["status"] };
            }),
          };
        })
      );
      if (withReport && task_key === "db_insert_report" && typeof output?.id === "number") {
        fetchReportById(output.id as number)
          .then((report) => updateMessage(asstMsgId, { report }))
          .catch(console.error);
      }
    },

    onFailed: (data: unknown) => {
      const { task_id, node_name, output } = data as {
        task_id: number; node_name: string; output?: Record<string, unknown>;
      };
      setMessages((prev) =>
        prev.map((m) => {
          if (m.id !== asstMsgId || !m.nodes) return m;
          return {
            ...m,
            nodes: m.nodes.map((ng) => {
              if (ng.node_name !== node_name) return ng;
              const tasks = ng.tasks.map((t) =>
                t.id === task_id ? { ...t, status: "failed" as const, output: output || t.output } : t
              );
              return { ...ng, tasks, status: "failed" as NodeGroup["status"] };
            }),
          };
        })
      );
    },

    onCancelled: (data: unknown) => {
      const { task_id, node_name } = data as { task_id: number; node_name: string };
      setMessages((prev) =>
        prev.map((m) => {
          if (m.id !== asstMsgId || !m.nodes) return m;
          return {
            ...m,
            nodes: m.nodes.map((ng) => {
              if (ng.node_name !== node_name) return ng;
              const tasks = ng.tasks.map((t) =>
                t.id === task_id ? { ...t, status: "cancelled" as const } : t
              );
              const allDone = tasks.every((t) =>
                ["completed", "failed", "cancelled"].includes(t.status)
              );
              return { ...ng, tasks, status: (allDone ? "completed" : ng.status) as NodeGroup["status"] };
            }),
          };
        })
      );
    },

    onDone: (data: unknown) => {
      const { status } = data as { status: string };
      if (status === "cancelled") {
        // Mark all still-running tasks and nodes as cancelled
        setMessages((prev) =>
          prev.map((m) => {
            if (m.id !== asstMsgId || !m.nodes) return m;
            return {
              ...m,
              nodes: m.nodes.map((ng) => {
                const tasks = ng.tasks.map((t) =>
                  t.status === "running" ? { ...t, status: "cancelled" as const } : t
                );
                const nodeStatus = ng.status === "running" ? ("cancelled" as const) : ng.status;
                return { ...ng, tasks, status: nodeStatus };
              }),
            };
          })
        );
      }
      onDone(status);
    },

    onClose,
  };
}
