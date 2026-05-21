/**
 * useThreadData — poll nodes and tasks after SSE events trigger a refresh.
 * Merges runtime nodes with the graph topology so nodes are revealed
 * progressively: only the direct successors (+1 depth) of any running or
 * completed node are shown as grey topology-only placeholders.  Deeper
 * nodes remain hidden until their predecessor has executed.
 *
 * If an initialTopology is provided (from the POST /threads/query response)
 * the separate GET /api/v1/graph/topology fetch is skipped entirely.
 */

import { useCallback, useEffect, useRef, useState } from 'react';
import { getGraphTopology, getNodes, getTasks, getThread } from '../api/threads';
import { getCachedThreadData, setCachedThreadData } from '../cache';
import { TERMINAL_QUERY_STATUSES } from '../constants/lifecycleStatus';
import type { GraphTopology, NodeInfo, QueryResponse, TaskInfo } from '../types';

interface ThreadData {
  thread: QueryResponse | null;
  nodes: NodeInfo[];
  tasks: TaskInfo[];
  topology: GraphTopology | null;
  refresh: () => void;
}

/** Merge runtime nodes with topology, revealing only:
 *  - Root nodes (no predecessors): always shown as grey if not yet executed.
 *  - Direct successors (+1 depth) of any running or completed node.
 *
 * If a node has no DB record but its tasks ran (e.g. quick routing node whose
 * node record hasn't propagated yet), the task status is used to synthesise a
 * non-placeholder node so it renders with the correct colour instead of dimmed.
 */
function mergeWithTopology(runtime: NodeInfo[], topology: GraphTopology, tasks: TaskInfo[], threadId: string): NodeInfo[] {
  // Build lookup: node_name → topology def
  const topoMap = new Map(topology.nodes.map(t => [t.node_name, t]));

  // Enrich runtime nodes with conditional_group and parallel_group from topology
  const enriched = runtime.map(n => {
    const topo = topoMap.get(n.node_name);
    if (topo?.conditional_group || topo?.parallel_group) {
      return {
        ...n,
        ...(topo.conditional_group ? { conditional_group: topo.conditional_group } : {}),
        ...(topo.parallel_group    ? { parallel_group:    topo.parallel_group    } : {}),
      };
    }
    return n;
  });

  // Build a task-based status lookup for nodes that may lack a DB record
  const taskStatusByNode = new Map<string, string>();
  for (const t of tasks) {
    const prev = taskStatusByNode.get(t.node_name);
    const rank = (s: string) => s === 'completed' ? 3 : s === 'running' ? 2 : s === 'failed' ? 1 : 0;
    if (!prev || rank(t.status) > rank(prev)) {
      taskStatusByNode.set(t.node_name, t.status);
    }
  }

  // Build successor and predecessor maps from topology edges
  const successorsOf = new Map<string, string[]>();
  const predecessorsOf = new Map<string, string[]>();
  for (const edge of topology.edges) {
    const succ = successorsOf.get(edge.from_node) ?? [];
    succ.push(edge.to_node);
    successorsOf.set(edge.from_node, succ);

    const pred = predecessorsOf.get(edge.to_node) ?? [];
    pred.push(edge.from_node);
    predecessorsOf.set(edge.to_node, pred);
  }

  // Root nodes (no predecessors): always visible as grey placeholders.
  const rootNames = new Set(
    topology.nodes
      .filter(n => !predecessorsOf.has(n.node_name))
      .map(n => n.node_name),
  );

  // Revealed grey set: roots + direct successors of running/completed nodes.
  const executedNames = new Set(runtime.map(n => n.node_name));
  const revealedUnrun = new Set<string>(rootNames);
  for (const n of enriched) {
    if (n.status === 'running' || n.status === 'completed') {
      for (const succ of (successorsOf.get(n.node_name) ?? [])) {
        if (!executedNames.has(succ)) revealedUnrun.add(succ);
      }
    }
  }

  // Add topology-only placeholder for revealed nodes not yet in runtime
  const runtimeNames = new Set(runtime.map(n => n.node_name));
  for (const topo of topology.nodes) {
    if (runtimeNames.has(topo.node_name)) continue;
    if (!revealedUnrun.has(topo.node_name)) continue;

    const inferredStatus = taskStatusByNode.get(topo.node_name);
    const isTopologyOnly = !inferredStatus;
    enriched.push({
      node_id: `topology-${topo.node_name}`,
      thread_id: threadId,
      node_name: topo.node_name,
      type: topo.node_type,
      status: inferredStatus ?? 'pending',
      elapsed_ms: 0,
      parallel_group: topo.parallel_group,
      conditional_group: topo.conditional_group,
      is_topology_only: isTopologyOnly,
    } as NodeInfo);
  }

  // Return in topology order
  const topoOrder = topology.nodes.map(t => t.node_name);
  const orderMap = new Map(topoOrder.map((name, i) => [name, i]));
  enriched.sort((a, b) => {
    const ai = orderMap.get(a.node_name) ?? 999;
    const bi = orderMap.get(b.node_name) ?? 999;
    return ai - bi;
  });

  return enriched;
}

export function useThreadData(threadId: string, initialTopology: GraphTopology | null = null): ThreadData {
  // Seed state from cache if this is a completed thread being revisited.
  const cached = getCachedThreadData(threadId);
  const [thread, setThread] = useState<QueryResponse | null>(cached?.thread ?? null);
  const [nodes, setNodes] = useState<NodeInfo[]>(cached?.nodes ?? []);
  const [tasks, setTasks] = useState<TaskInfo[]>(cached?.tasks ?? []);
  const [topology, setTopology] = useState<GraphTopology | null>(cached?.topology ?? initialTopology);
  const pendingRef = useRef(false);
  // When a refresh is in-flight and another is requested, set this flag so a
  // follow-up refresh fires once the current one completes.  This prevents
  // concurrent task_status SSE events from being silently dropped, which would
  // leave some tasks showing 'running' forever in a parallel-streaming scenario.
  const dirtyRef = useRef(false);
  // Seed the ref immediately so the first refresh() can skip the fetch.
  const topologyRef = useRef<GraphTopology | null>(cached?.topology ?? initialTopology);

  const refresh = useCallback(() => {
    if (pendingRef.current) {
      dirtyRef.current = true;
      return;
    }
    pendingRef.current = true;
    dirtyRef.current = false;

    const topoPromise: Promise<GraphTopology> = topologyRef.current
      ? Promise.resolve(topologyRef.current)
      : getGraphTopology().then(t => { topologyRef.current = t; return t; });

    Promise.all([getThread(threadId), getNodes(threadId), getTasks(threadId), topoPromise])
      .then(([t, n, k, topo]) => {
        const mergedNodes = mergeWithTopology(n, topo, k, threadId);
        setThread(t);
        setNodes(mergedNodes);
        setTasks(k);
        setTopology(topo);
        if (TERMINAL_QUERY_STATUSES.has(t.status as never)) {
          setCachedThreadData({ thread: t, nodes: mergedNodes, tasks: k, topology: topo });
        }
      })
      .catch(() => {/* ignore transient errors */})
      .finally(() => {
        pendingRef.current = false;
        if (dirtyRef.current) {
          dirtyRef.current = false;
          refresh();
        }
      });
  }, [threadId]);

  // Initial load: skip fetch if we already seeded state from cache (terminal thread).
  useEffect(() => {
    if (getCachedThreadData(threadId)) return;
    refresh();
  }, [refresh, threadId]);

  return { thread, nodes, tasks, topology, refresh };
}

export { TERMINAL_QUERY_STATUSES as TERMINAL };
