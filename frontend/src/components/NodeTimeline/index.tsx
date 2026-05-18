/**
 * NodeTimeline — hierarchical sectioned bar timeline.
 *
 * Root bar: top-level nodes (no parent_node_id) as positioned sections.
 * Subgraph nodes (type === "Subgraph") expand on click to reveal a child bar
 * row below, recursively. Leaf nodes expand to show task-level Gantt rows.
 *
 * Narrow sections (< NARROW_PCT % of track) omit the inline elapsed label;
 * it is shown instead in the left label area on hover.
 *
 * All large wall-clock gaps (> GAP_THRESHOLD_MS) in the current view are
 * auto-detected and compressed into narrow shaded rectangles.  This handles
 * both the fork-branch gap and internal gaps from slow parallel nodes.
 */

import React, { useCallback, useEffect, useMemo, useState } from 'react';
import type { NodeInfo, TaskInfo } from '../../types';
import { COLOR_TEXT_ACTIVE, COLOR_TEXT_FAINT } from '../../constants/styleColors';
import { buildChildrenMap, buildEffectiveSpans, buildNodeTaskMap, buildOverlapRects, formatMs } from './utils';
import type { GapSegment } from './utils';
import { AXIS_TICKS, GAP_VISUAL_PCT, LABEL_W } from './constants';
import BarRow from './BarRow';

/** Gap threshold in ms above which the timeline auto-compresses the gap. */
const GAP_THRESHOLD_MS = 2_000;

interface Props {
  nodes: NodeInfo[];
  tasks: TaskInfo[];
  selectedNodeId: string | null;
  onSelectNode: (nodeId: string) => void;
  /** When set, the timeline shows a shaded separator at the fork point and
   *  compresses any large wall-clock gap between shared and new branch nodes. */
  forkNode?: NodeInfo | null;
}

function NodeTimeline({ nodes, tasks, selectedNodeId, onSelectNode, forkNode }: Props) {
  // Topology-only nodes have no timing data (started_at undefined → startMs=0),
  // which would corrupt tMin and compress all real bars to the far right.
  const activeNodes = useMemo(() => nodes.filter(n => !n.is_topology_only), [nodes]);
  const [hoveredNodeId, setHoveredNodeId]           = useState<string | null>(null);
  const [hoveredTaskId, setHoveredTaskId]           = useState<string | null>(null);
  /** Set of subgraph node_ids whose children row is currently visible. */
  const [expandedSubgraphs, setExpandedSubgraphs]   = useState<Set<string>>(new Set());
  /** At most one leaf node shows its task Gantt at a time. */
  const [expandedTaskNodeId, setExpandedTaskNodeId] = useState<string | null>(null);
  /** Set of row keys whose parallel nodes are shown in separate lanes. */
  const [expandedParallelRows, setExpandedParallelRows] = useState<Set<string>>(new Set());

  const handleToggleParallelRow = useCallback((key: string) => {
    setExpandedParallelRows(prev => {
      const next = new Set(prev);
      next.has(key) ? next.delete(key) : next.add(key);
      return next;
    });
  }, []);

  const nodeTaskMap    = useMemo(() => buildNodeTaskMap(tasks), [tasks]);
  const childrenMap    = useMemo(() => buildChildrenMap(activeNodes), [activeNodes]);
  const effectiveSpans = useMemo(
    () => buildEffectiveSpans(activeNodes, nodeTaskMap, childrenMap),
    [activeNodes, nodeTaskMap, childrenMap],
  );

  // Auto-expand rows that contain overlapping parallel nodes.
  useEffect(() => {
    setExpandedParallelRows(prev => {
      let changed = false;
      const next = new Set(prev);
      const roots = childrenMap.get(null) ?? [];
      if (buildOverlapRects(roots, effectiveSpans).length > 0 && !next.has('root')) {
        next.add('root'); changed = true;
      }
      for (const n of activeNodes) {
        if (n.type === 'Subgraph') {
          const key = `sg:${n.node_id}`;
          const children = childrenMap.get(n.node_id) ?? [];
          if (buildOverlapRects(children, effectiveSpans).length > 0 && !next.has(key)) {
            next.add(key); changed = true;
          }
        }
      }
      return changed ? next : prev;
    });
}, [childrenMap, effectiveSpans, activeNodes]);

  const { tMin, totalMs } = useMemo(() => {
    let mn = Infinity, mx = -Infinity;
    for (const [, sp] of effectiveSpans) {
      mn = Math.min(mn, sp.startMs);
      mx = Math.max(mx, sp.endMs);
    }
    return {
      tMin:    mn === Infinity  ? 0 : mn,
      totalMs: Math.max((mx === -Infinity ? 1 : mx) - (mn === Infinity ? 0 : mn), 1),
    };
  }, [effectiveSpans]);

  // ── Multi-gap compression ──────────────────────────────────────────────
  //
  // Detect every large wall-clock gap in the current view (between any two
  // consecutive "clusters" of activity) and compress each one to a narrow
  // shaded rectangle.  This handles both the fork-branch gap AND any internal
  // gap caused by a slow parallel node that ran much later than its siblings.
  const gaps = useMemo((): GapSegment[] => {
    const intervals: [number, number][] = [];
    for (const [, sp] of effectiveSpans) {
      intervals.push([sp.startMs - tMin, sp.endMs - tMin]);
    }
    if (intervals.length <= 1) return [];

    // Sort and merge overlapping / touching intervals.
    intervals.sort((a, b) => a[0] - b[0]);
    const merged: [number, number][] = [[...intervals[0]]];
    for (const [s, e] of intervals.slice(1)) {
      const last = merged[merged.length - 1];
      if (s <= last[1] + 1) {
        last[1] = Math.max(last[1], e);
      } else {
        merged.push([s, e]);
      }
    }

    // Find gaps between consecutive merged intervals.
    const result: GapSegment[] = [];
    for (let i = 0; i < merged.length - 1; i++) {
      const gapStart = merged[i][1];
      const gapEnd   = merged[i + 1][0];
      if (gapEnd - gapStart > GAP_THRESHOLD_MS) {
        result.push({ gapStart, gapEnd });
      }
    }

    // Annotate the gap that immediately precedes the re-explore fork branch.
    if (forkNode?.started_at) {
      const forkStartRel = new Date(forkNode.started_at).getTime() - tMin;
      // Find the gap whose gapEnd is closest to forkStartRel and comes before it.
      let bestIdx = -1, bestDist = Infinity;
      for (let i = 0; i < result.length; i++) {
        if (forkStartRel >= result[i].gapStart) {
          const dist = Math.abs(result[i].gapEnd - forkStartRel);
          if (dist < bestDist) { bestDist = dist; bestIdx = i; }
        }
      }
      if (bestIdx >= 0) {
        result[bestIdx].forkVersion  = forkNode.version ?? 0;
        result[bestIdx].forkNodeName = forkNode.node_name;
      }
    }

    return result;
  }, [effectiveSpans, tMin, forkNode]);

  // Build the (possibly multi-segmented) pct mapper.
  // For positions: pct(ms) maps a time offset (relative to tMin) to a [0,100] %.
  // For widths: pct(duration) gives the same value as pct(end)-pct(start) for any
  // bar that does not span a gap, because all actual-content segments share the
  // same global scale factor (1/totalActualMs * availableWidth).
  const pct = useCallback((ms: number): number => {
    if (gaps.length === 0) return (ms / totalMs) * 100;

    const totalGapMs    = gaps.reduce((acc, g) => acc + (g.gapEnd - g.gapStart), 0);
    const totalActualMs = Math.max(totalMs - totalGapMs, 1);
    const availableWidth = 100 - gaps.length * GAP_VISUAL_PCT;

    let pos     = 0;
    let prevEnd = 0;
    for (const gap of gaps) {
      const segMs = gap.gapStart - prevEnd;
      if (ms <= gap.gapStart) {
        const inSeg = ms - prevEnd;
        if (segMs <= 0) return pos;
        return pos + (inSeg / totalActualMs) * availableWidth;
      }
      if (segMs > 0) pos += (segMs / totalActualMs) * availableWidth;
      if (ms < gap.gapEnd) {
        const frac = (ms - gap.gapStart) / Math.max(gap.gapEnd - gap.gapStart, 1);
        return pos + frac * GAP_VISUAL_PCT;
      }
      pos    += GAP_VISUAL_PCT;
      prevEnd = gap.gapEnd;
    }
    // After all gaps — last segment.
    const inSeg = ms - prevEnd;
    const segMs = totalMs - prevEnd;
    if (segMs <= 0) return pos;
    return pos + (inSeg / totalActualMs) * availableWidth;
  }, [gaps, totalMs]);

  // Filter axis ticks so none fall inside any compressed gap region.
  const visibleTicks = useMemo(() => {
    if (gaps.length === 0) return AXIS_TICKS;
    return AXIS_TICKS.filter(f => {
      const ms = f * totalMs;
      return !gaps.some(g => ms > g.gapStart && ms < g.gapEnd);
    });
  }, [gaps, totalMs]);

  const isExpanded = expandedSubgraphs.size > 0 || expandedTaskNodeId !== null || expandedParallelRows.size > 0;

  const handleCollapseAll = useCallback(() => {
    setExpandedSubgraphs(new Set());
    setExpandedTaskNodeId(null);
    setExpandedParallelRows(new Set());
  }, []);

  const handleNodeClick = useCallback((node: NodeInfo) => {
    onSelectNode(node.node_id);
    if (node.type === 'Subgraph') {
      setExpandedSubgraphs(prev => {
        const next = new Set(prev);
        next.has(node.node_id) ? next.delete(node.node_id) : next.add(node.node_id);
        return next;
      });
    } else {
      const hasTasks = (nodeTaskMap.get(node.node_id) ?? []).length > 0;
      if (hasTasks) {
        setExpandedTaskNodeId(prev => prev === node.node_id ? null : node.node_id);
      }
    }
  }, [nodeTaskMap, onSelectNode]);

  const roots = childrenMap.get(null) ?? [];

  return (
    <div style={{ fontFamily: 'monospace', fontSize: 12, color: COLOR_TEXT_ACTIVE, userSelect: 'none', position: 'relative' }}>
      {/* ── Time axis — hidden when nothing is expanded (shrunken state) ── */}
      {isExpanded && (
        <div style={{ display: 'flex', marginLeft: LABEL_W, marginBottom: 4, position: 'relative', height: 16 }}>
          {visibleTicks.map(f => (
            <div
              key={f}
              style={{
                position: 'absolute', left: `${pct(f * totalMs)}%`,
                transform: 'translateX(-50%)', color: COLOR_TEXT_FAINT, fontSize: 10,
              }}
            >
              {formatMs(f * totalMs)}
            </div>
          ))}
        </div>
      )}

      <BarRow
        rowKey="root"
        rowNodes={roots}
        indent={0}
        fallbackLabel="nodes"
        gaps={gaps}
        hoveredNodeId={hoveredNodeId}
        setHoveredNodeId={setHoveredNodeId}
        hoveredTaskId={hoveredTaskId}
        setHoveredTaskId={setHoveredTaskId}
        expandedSubgraphs={expandedSubgraphs}
        expandedTaskNodeId={expandedTaskNodeId}
        expandedParallelRows={expandedParallelRows}
        onToggleParallelRow={handleToggleParallelRow}
        nodeTaskMap={nodeTaskMap}
        childrenMap={childrenMap}
        effectiveSpans={effectiveSpans}
        pct={pct}
        tMin={tMin}
        onSelectNode={onSelectNode}
        onNodeClick={handleNodeClick}
        onCollapseAll={isExpanded ? handleCollapseAll : undefined}
      />
    </div>
  );
}

export default NodeTimeline;

