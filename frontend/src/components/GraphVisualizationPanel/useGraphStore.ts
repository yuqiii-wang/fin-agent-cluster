import { useCallback, useReducer } from "react";
import type { GraphEvent, GraphNode, GraphState, GraphTask, GraphTopology } from "./types";
import { EMPTY_GRAPH_STATE } from "./types";

// ── Synthetic execution IDs for pre-created subgraph container nodes ──────────
// Negative to avoid collision with real DB PKs (always > 0).
const SYNTHETIC_ID_BASE = -1000;
function syntheticId(index: number): number {
  return SYNTHETIC_ID_BASE - index;
}

/** Derive the runtime status of a subgraph container from its inner nodes. */
function deriveContainerStatus(innerNodes: GraphNode[]): GraphNode["status"] {
  if (innerNodes.length === 0) return "pending";
  if (innerNodes.some((n) => n.status === "running")) return "running";
  if (innerNodes.some((n) => n.status === "failed")) return "failed";
  if (innerNodes.some((n) => n.status === "cancelled")) return "cancelled";
  if (innerNodes.every((n) => n.status === "completed")) return "completed";
  // Some completed, none running → still working (more nodes may arrive)
  return "running";
}

/**
 * Rebuild container-node statuses based on current inner nodes.
 * Returns the nodes array with updated synthetic container entries.
 */
function syncContainerStatuses(nodes: GraphNode[]): GraphNode[] {
  const hasSynthetic = nodes.some((n) => n.is_synthetic);
  if (!hasSynthetic) return nodes;

  return nodes.map((n) => {
    if (!n.is_synthetic || n.node_type !== "Subgraph") return n;
    const innerNodes = nodes.filter((x) => x.subgraph_parent === n.node_name);
    const derivedStatus = deriveContainerStatus(innerNodes);
    if (derivedStatus === n.status) return n;
    return { ...n, status: derivedStatus };
  });
}

function applyEvent(state: GraphState, event: GraphEvent): GraphState {
  switch (event.type) {
    case "reset":
      return EMPTY_GRAPH_STATE;

    case "graph_topology_init": {
      const topology: GraphTopology = {
        outer_nodes: event.outer_nodes,
        subgraphs: event.subgraphs,
      };
      // Pre-create synthetic pending nodes for outer nodes (including subgraph containers).
      // These are replaced/updated as real SSE events arrive.
      const syntheticNodes: GraphNode[] = event.outer_nodes.map((n, i) => ({
        node_execution_id: syntheticId(i),
        parent_node_execution_ids: [],  // outer view uses name-based edges, not ID-based
        node_name: n.node_name,
        status: "pending" as const,
        started_at_ms: 0,
        node_type: n.node_type,
        is_synthetic: true,
      }));
      return { ...EMPTY_GRAPH_STATE, nodes: syntheticNodes, topology };
    }

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
        node_type: event.node_type,
        subgraph_parent: event.subgraph_parent,
      };
      // On resume, a node that ran before re-runs with a new node_execution_id.
      // Replace the stale entry regardless of status so the DAG stays clean
      // and purge its associated tasks (they will be re-emitted).
      // For synthetic outer nodes, keep them — they are in a different scope.
      const staleIdx = state.nodes.findIndex(
        (n) => !n.is_synthetic && n.node_name === event.node_name,
      );
      let updatedNodes: GraphNode[];
      let updatedTasks: GraphTask[];
      if (staleIdx >= 0) {
        updatedNodes = [...state.nodes];
        updatedNodes[staleIdx] = newNode;
        const staleName = state.nodes[staleIdx].node_name;
        updatedTasks = state.tasks.filter((t) => t.node_name !== staleName);
      } else {
        updatedNodes = [...state.nodes, newNode];
        updatedTasks = state.tasks;
      }
      return { ...state, nodes: syncContainerStatuses(updatedNodes), tasks: updatedTasks };
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
      return { ...state, nodes: syncContainerStatuses(updated) };
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
        return { ...state, nodes: syncContainerStatuses(updated) };
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

