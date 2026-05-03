import type React from "react";
import type { ChatMessage, NodeGroup, SseNodeStatus, TaskInfo } from "../types";

interface SseHandlerParams {
  asstMsgId: string;
  threadId: string;
  setMessages: React.Dispatch<React.SetStateAction<ChatMessage[]>>;
  /** Buffer a token delta for a task; caller flushes to state on a schedule. */
  pushTokenStream: (taskId: string, token: string) => void;
  setTaskProviders: React.Dispatch<React.SetStateAction<Record<number, string>>>;
  appendMessageText: (msgId: string, token: string) => void;
  updateMessage: (msgId: string, patch: Partial<ChatMessage>) => void;
  onDone: (status: string) => void;
  onClose: () => void;
  /**
   * Called when the SSE connection itself fails before any task events are received
   * (e.g. TLS certificate not accepted).  Receives the human-readable error message.
   * When omitted, falls back to calling `onClose`.
   */
  onConnectionFailed?: (message: string) => void;
  /** Called when the query resumes from cancelled/failed state and the graph begins re-executing. */
  onResumed?: () => void;
}

export function buildSseHandlers({
  asstMsgId,
  threadId,
  setMessages,
  pushTokenStream,
  setTaskProviders,
  appendMessageText,
  updateMessage,
  onDone,
  onClose,
  onConnectionFailed,
  onResumed,
}: SseHandlerParams) {
  return {
    /** When the graph resumes after cancellation, flip message status back to running. */
    onQueryStatus: (data: unknown) => {
      const { phase } = data as { phase?: string };
      if (phase === "preparing" || phase === "running") {
        updateMessage(asstMsgId, { status: "running" as ChatMessage["status"], streamingCursor: false });
        onResumed?.();
      }
    },

    onStarted: (data: unknown) => {
      const { task_id, node_name, task_name, provider, node_id } = data as {
        task_id: string; node_name: string; task_name: string; provider?: string; node_id?: string;
      };
      if (provider) setTaskProviders((prev) => ({ ...prev, [task_id]: provider }));
      const newTask: TaskInfo = {
        task_id,
        thread_id: threadId,
        node_execution_id: null,
        node_name,
        task_name,
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
                  ? {
                      ...n,
                      status: "running" as const,
                      node_id: node_id ?? n.node_id,
                      tasks: [...n.tasks, newTask],
                    }
                  : n
              ),
            };
          }
          return {
            ...m,
            nodes: [...nodes, { node_name, node_id, status: "running" as const, tasks: [newTask] }],
          };
        })
      );
    },

    onToken: (data: unknown) => {
      const { task_id, task_name, data: token } = data as {
        task_id: string; task_name: string; data: string;
      };
      if (task_name === "llm_analysis") appendMessageText(asstMsgId, token);
      pushTokenStream(task_id, token);
    },

    onCompleted: (data: unknown) => {
      const { task_id, node_name, task_name, output } = data as {
        task_id: string; node_name: string; task_name: string; output: Record<string, unknown>;
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
                t.task_id === task_id
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
    },

    onFailed: (data: unknown) => {
      const { task_id, node_name, output, message } = data as {
        task_id?: string; node_name?: string; output?: Record<string, unknown>; message?: string;
      };
      // Connection-level failure (e.g. TLS cert not accepted) — no task_id present.
      if (task_id == null) {
        const errMsg = message ?? "SSE connection failed";
        if (onConnectionFailed) {
          onConnectionFailed(errMsg);
        } else {
          onClose();
        }
        return;
      }
      // Extract structured error fields from the task output payload.
      const taskError = (output?.error as string | undefined) ?? message;
      const taskErrorCode = output?.error_code as string | undefined;
      const taskErrorDescription = output?.error_description as string | undefined;
      setMessages((prev) =>
        prev.map((m) => {
          if (m.id !== asstMsgId || !m.nodes) return m;
          return {
            ...m,
            nodes: m.nodes.map((ng) => {
              if (ng.node_name !== node_name) return ng;
              const tasks = ng.tasks.map((t) =>
                t.task_id === task_id
                  ? {
                      ...t,
                      status: "failed" as const,
                      output: output || t.output,
                      ...(taskError ? { error: taskError } : {}),
                      ...(taskErrorCode ? { error_code: taskErrorCode } : {}),
                      ...(taskErrorDescription ? { error_description: taskErrorDescription } : {}),
                    }
                  : t
              );
              return { ...ng, tasks, status: "failed" as NodeGroup["status"] };
            }),
          };
        })
      );
    },

    onCancelled: (data: unknown) => {
      const { task_id, node_name } = data as { task_id: string; node_name: string };
      setMessages((prev) =>
        prev.map((m) => {
          if (m.id !== asstMsgId || !m.nodes) return m;
          return {
            ...m,
            nodes: m.nodes.map((ng) => {
              if (ng.node_name !== node_name) return ng;
              const tasks = ng.tasks.map((t) =>
                t.task_id === task_id ? { ...t, status: "cancelled" as const } : t
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

    onNodeStatus: (data: unknown) => {
      const { node_id, node_name, status } = data as SseNodeStatus;
      setMessages((prev) =>
        prev.map((m) => {
          if (m.id !== asstMsgId || !m.nodes) return m;
          return {
            ...m,
            nodes: m.nodes.map((ng) => {
              // Match by node_id (if present) or node_name fallback.
              const matches = (ng.node_id && ng.node_id === node_id) ||
                (!ng.node_id && ng.node_name === node_name);
              if (!matches) return ng;
              return {
                ...ng,
                node_id: node_id || ng.node_id,
                status: status as NodeGroup["status"],
              };
            }),
          };
        })
      );
    },

    onDone: (data: unknown) => {
      const { status, error_code, error_description } = data as {
        status: string;
        error_code?: string;
        error_description?: string;
      };
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
      } else if (status === "failed") {
        // Mark all still-running tasks and nodes as failed (graph aborted).
        // Attach the graph-level error_code/description so the tooltip shows
        // the reason even for tasks that had no individual fail_task call.
        setMessages((prev) =>
          prev.map((m) => {
            if (m.id !== asstMsgId || !m.nodes) return m;
            return {
              ...m,
              nodes: m.nodes.map((ng) => {
                const tasks = ng.tasks.map((t) =>
                  t.status === "running"
                    ? {
                        ...t,
                        status: "failed" as const,
                        ...(error_code && !t.error_code ? { error_code } : {}),
                        ...(error_description && !t.error_description ? { error_description } : {}),
                      }
                    : t
                );
                const nodeStatus = ng.status === "running" ? ("failed" as const) : ng.status;
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
