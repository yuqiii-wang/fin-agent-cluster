import { useCallback, useReducer } from "react";
import type { GraphEvent, GraphNode, GraphState, GraphTask } from "./types";
import { EMPTY_GRAPH_STATE } from "./types";

function applyEvent(state: GraphState, event: GraphEvent): GraphState {
  switch (event.type) {
    case "reset":
      return EMPTY_GRAPH_STATE;

    case "node_input": {
      // Avoid exact duplicates (history re-delivery by same node_execution_id).
      if (state.nodes.some((n) => n.node_execution_id === event.node_execution_id)) return state;
      const newNode: GraphNode = {
        node_execution_id: event.node_execution_id,
        parent_node_execution_ids: event.parent_node_execution_ids,
        node_name: event.node_name,
        status: "running",
        started_at_ms: event.ts,
        input: event.input,
      };
      // On resume, a node that ran before re-runs with a new node_execution_id.
      // Replace the stale entry regardless of status so the DAG stays clean
      // and purge its associated tasks (they will be re-emitted).
      const staleIdx = state.nodes.findIndex(
        (n) => n.node_name === event.node_name,
      );
      if (staleIdx >= 0) {
        const updatedNodes = [...state.nodes];
        updatedNodes[staleIdx] = newNode;
        const staleName = state.nodes[staleIdx].node_name;
        const updatedTasks = state.tasks.filter((t) => t.node_name !== staleName);
        return { ...state, nodes: updatedNodes, tasks: updatedTasks };
      }
      return { ...state, nodes: [...state.nodes, newNode] };
    }

    case "node_output": {
      const idx = state.nodes.findIndex((n) => n.node_execution_id === event.node_execution_id);
      if (idx < 0) return state;
      const updated = [...state.nodes];
      const prev = updated[idx];
      updated[idx] = {
        ...prev,
        status: "completed",
        // Prefer server-stamped ended_at_ms; fall back to started_at_ms + elapsed_ms.
        ended_at_ms: event.ended_at_ms ?? (prev.started_at_ms + event.elapsed_ms),
        elapsed_ms: event.elapsed_ms,
        output: event.output,
      };
      return { ...state, nodes: updated };
    }

    case "node_status": {
      const isTerminal = ["completed", "failed", "cancelled"].includes(event.status);
      // Match by node_id if already set, or by node_name for the most recent running node
      const idx = state.nodes.findIndex((n) =>
        n.node_id ? n.node_id === event.node_id : n.node_name === event.node_name && n.status === "running",
      );
      if (idx >= 0) {
        const updated = [...state.nodes];
        const prev = updated[idx];
        updated[idx] = {
          ...prev,
          node_id: event.node_id,
          status: event.status as GraphNode["status"],
          ...(isTerminal && !prev.ended_at_ms
            ? {
                ended_at_ms: event.ended_at_ms ?? event.ts,
                elapsed_ms: (event.ended_at_ms ?? event.ts) - prev.started_at_ms,
              }
            : {}),
        };
        return { ...state, nodes: updated };
      }
      return state;
    }

    case "task_started": {
      if (state.tasks.some((t) => t.task_id === event.task_id)) return state;
      const newTask: GraphTask = {
        task_id: event.task_id,
        node_name: event.node_name,
        task_name: event.task_name,
        status: "running",
        started_at_ms: event.ts,
        input: event.input,
        output: {},
      };
      return { ...state, tasks: [...state.tasks, newTask] };
    }

    case "task_terminal": {
      const idx = state.tasks.findIndex((t) => t.task_id === event.task_id);
      if (idx >= 0) {
        const updated = [...state.tasks];
        const prev = updated[idx];
        updated[idx] = {
          ...prev,
          status: event.status as GraphTask["status"],
          ended_at_ms: event.ts,
          elapsed_ms: event.ts - prev.started_at_ms,
          output: (event.output ?? {}) as Record<string, unknown>,
        };
        return { ...state, tasks: updated };
      }
      // Task terminal before "started" (late history delivery) — insert completed directly
      return {
        ...state,
        tasks: [
          ...state.tasks,
          {
            task_id: event.task_id,
            node_name: event.node_name,
            task_name: event.task_name,
            status: event.status as GraphTask["status"],
            started_at_ms: event.ts,
            ended_at_ms: event.ts,
            elapsed_ms: 0,
            output: (event.output ?? {}) as Record<string, unknown>,
          },
        ],
      };
    }

    case "done":
      // When the graph is paused, any tasks still in "running" state were not
      // cleanly terminated (e.g. streaming tasks via Celery).  Remove them so
      // the UI shows a clean slate — they will re-appear when the run resumes.
      // Also mark any running nodes as "paused" — the backend emits done(paused)
      // instead of a node_status("paused") event, so we derive node status here.
      if (event.status === "paused") {
        const pausedNodes = state.nodes.map((n) =>
          n.status === "running" ? { ...n, status: "paused" as const } : n,
        );
        const nonRunningTasks = state.tasks.filter((t) => t.status !== "running");
        return { ...state, nodes: pausedNodes, tasks: nonRunningTasks, isDone: true, doneStatus: event.status };
      }
      return { ...state, isDone: true, doneStatus: event.status };

    default:
      return state;
  }
}

export function useGraphStore() {
  const [graphState, dispatch] = useReducer(applyEvent, EMPTY_GRAPH_STATE);

  const dispatchEvent = useCallback((event: GraphEvent) => {
    dispatch(event);
  }, []);

  const resetGraph = useCallback(() => {
    dispatch({ type: "reset" });
  }, []);

  return { graphState, dispatchEvent, resetGraph };
}

