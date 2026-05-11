import type { NodeInfo, TaskInfo } from '../../types';

export interface EffectiveSpan { startMs: number; endMs: number; elapsedMs: number; }

export function buildNodeTaskMap(tasks: TaskInfo[]): Map<string, TaskInfo[]> {
  const map = new Map<string, TaskInfo[]>();
  for (const t of tasks) {
    const key = t.node_id ?? '__unassigned__';
    const arr = map.get(key) ?? [];
    arr.push(t);
    map.set(key, arr);
  }
  return map;
}

/** Map parent_node_id → children. Key null = root nodes. */
export function buildChildrenMap(nodes: NodeInfo[]): Map<string | null, NodeInfo[]> {
  const map = new Map<string | null, NodeInfo[]>();
  for (const n of nodes) {
    const key = n.parent_node_id ?? null;
    const arr = map.get(key) ?? [];
    arr.push(n);
    map.set(key, arr);
  }
  return map;
}

/**
 * Computes effective time spans bottom-up:
 *   task timestamps  →  typical node span  →  subgraph span
 * A node's span is the union of its own started_at/elapsed_ms with:
 *   - all its tasks (for typical nodes)
 *   - all its children's effective spans (for subgraph nodes)
 */
export function buildEffectiveSpans(
  nodes: NodeInfo[],
  nodeTaskMap: Map<string, TaskInfo[]>,
  childrenMap: Map<string | null, NodeInfo[]>,
): Map<string, EffectiveSpan> {
  const cache = new Map<string, EffectiveSpan>();

  function compute(node: NodeInfo): EffectiveSpan {
    if (cache.has(node.node_id)) return cache.get(node.node_id)!;
    const nodeStart = node.started_at ? new Date(node.started_at).getTime() : 0;
    let start = nodeStart;
    let end   = nodeStart + Math.max(node.elapsed_ms ?? 0, 0);

    if (node.type === 'Subgraph') {
      for (const child of childrenMap.get(node.node_id) ?? []) {
        const cs = compute(child);
        start = Math.min(start, cs.startMs);
        end   = Math.max(end,   cs.endMs);
      }
    } else {
      for (const task of nodeTaskMap.get(node.node_id) ?? []) {
        const ts = task.created_at ? new Date(task.created_at).getTime() : nodeStart;
        const te = task.updated_at  ? new Date(task.updated_at).getTime()  : ts + 1;
        start = Math.min(start, ts);
        end   = Math.max(end, te);
      }
    }

    const span: EffectiveSpan = { startMs: start, endMs: end, elapsedMs: end - start };
    cache.set(node.node_id, span);
    return span;
  }

  for (const n of nodes) compute(n);
  return cache;
}

export function formatMs(ms: number): string {
  if (ms < 1000) return `${ms}ms`;
  if (ms < 60_000) return `${(ms / 1000).toFixed(1)}s`;
  return `${(ms / 60_000).toFixed(1)}m`;
}

/**
 * Returns merged overlap intersection rects (in ms) for a set of nodes.
 * Used to render shrunken-bar overlap highlights.
 */
export function buildOverlapRects(
  nodes: NodeInfo[],
  spans: Map<string, EffectiveSpan>,
): Array<{ startMs: number; endMs: number }> {
  const raw: Array<{ startMs: number; endMs: number }> = [];
  for (let i = 0; i < nodes.length; i++) {
    for (let j = i + 1; j < nodes.length; j++) {
      const a = spans.get(nodes[i].node_id);
      const b = spans.get(nodes[j].node_id);
      if (!a || !b) continue;
      const s = Math.max(a.startMs, b.startMs);
      const e = Math.min(a.endMs, b.endMs);
      if (s < e) raw.push({ startMs: s, endMs: e });
    }
  }
  raw.sort((a, b) => a.startMs - b.startMs);
  const merged: Array<{ startMs: number; endMs: number }> = [];
  for (const r of raw) {
    const last = merged[merged.length - 1];
    if (last && r.startMs <= last.endMs) {
      last.endMs = Math.max(last.endMs, r.endMs);
    } else {
      merged.push({ ...r });
    }
  }
  return merged;
}

/**
 * Greedy interval scheduling: assigns each node to the earliest available
 * lane so that no two nodes in the same lane overlap.
 */
export function assignLanes(
  nodes: NodeInfo[],
  spans: Map<string, EffectiveSpan>,
): { lanes: Map<string, number>; laneCount: number } {
  const sorted = [...nodes].sort((a, b) => {
    const sa = spans.get(a.node_id)?.startMs ?? 0;
    const sb = spans.get(b.node_id)?.startMs ?? 0;
    return sa - sb;
  });
  const lanes = new Map<string, number>();
  const laneEndTimes: number[] = [];
  for (const node of sorted) {
    const span  = spans.get(node.node_id);
    const start = span?.startMs ?? 0;
    const end   = span?.endMs   ?? start + 1;
    let assigned = -1;
    for (let i = 0; i < laneEndTimes.length; i++) {
      if (laneEndTimes[i] <= start) {
        assigned = i;
        laneEndTimes[i] = end;
        break;
      }
    }
    if (assigned === -1) {
      assigned = laneEndTimes.length;
      laneEndTimes.push(end);
    }
    lanes.set(node.node_id, assigned);
  }
  return { lanes, laneCount: laneEndTimes.length };
}
