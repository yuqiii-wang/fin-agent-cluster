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
 * When ``forkNode`` is provided (for re-explore version views), a large
 * wall-clock gap between the shared nodes and the new branch is visually
 * compressed: the gap collapses to a narrow dashed separator line.
 */

import React, { useCallback, useEffect, useMemo, useState } from 'react';
import type { NodeInfo, TaskInfo } from '../../types';
import { COLOR_SURFACE_CARD, COLOR_TEXT_ACTIVE, COLOR_TEXT_FAINT, COLOR_TEXT_MUTED, COLOR_TEXT_SECONDARY } from '../../constants/styleColors';
import { buildChildrenMap, buildEffectiveSpans, buildNodeTaskMap, buildOverlapRects, formatMs } from './utils';
import { AXIS_TICKS, LABEL_W } from './constants';
import BarRow from './BarRow';

/** Gap threshold in ms above which the timeline compresses the re-explore gap. */
const RE_EXPLORE_GAP_THRESHOLD_MS = 2_000;
/** Visual width (%) allocated to the compressed gap separator. */
const GAP_VISUAL_PCT = 2;

interface Props {
  nodes: NodeInfo[];
  tasks: TaskInfo[];
  selectedNodeId: string | null;
  onSelectNode: (nodeId: string) => void;
  /** When set, the timeline shows a dashed separator at the fork point and
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
  const [forkLineHovered, setForkLineHovered]       = useState(false);

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

  // ── Re-explore gap compression ───────────────────────────────────────────
  //
  // When viewing a forked version, compute whether the wall-clock gap between
  // shared nodes and the new branch is large enough to compress visually.
  const gapInfo = useMemo(() => {
    if (!forkNode || !forkNode.started_at) return null;
    const forkVersion = forkNode.version ?? 0;
    const forkStartMs = new Date(forkNode.started_at).getTime();

    // Find the end of the latest shared node (any node with version < forkVersion).
    let sharedEndMs = -Infinity;
    for (const n of activeNodes) {
      if ((n.version ?? 0) >= forkVersion) continue;
      const sp = effectiveSpans.get(n.node_id);
      if (sp) sharedEndMs = Math.max(sharedEndMs, sp.endMs);
    }
    if (sharedEndMs === -Infinity) return null;

    const gapMs = forkStartMs - sharedEndMs;
    if (gapMs <= RE_EXPLORE_GAP_THRESHOLD_MS) return null;

    // Relative to tMin
    const sharedEndRel = sharedEndMs - tMin;
    const forkStartRel = forkStartMs - tMin;
    const sharedDuration = sharedEndRel;
    const newDuration = totalMs - forkStartRel;

    if (sharedDuration <= 0 || newDuration <= 0) return null;

    const effectiveTotal = sharedDuration + newDuration;
    const section1Width = (sharedDuration / effectiveTotal) * (100 - GAP_VISUAL_PCT);
    const section2Start = section1Width + GAP_VISUAL_PCT;
    const section2Width = 100 - section2Start;
    const dashLinePct   = section1Width + GAP_VISUAL_PCT / 2;

    return { sharedEndRel, forkStartRel, section1Width, section2Start, section2Width, dashLinePct };
  }, [forkNode, activeNodes, effectiveSpans, tMin, totalMs]);

  // Build the (possibly segmented) pct mapper.
  const pct = useCallback((ms: number): number => {
    if (!gapInfo) return (ms / totalMs) * 100;
    const { sharedEndRel, forkStartRel, section1Width, section2Start, section2Width } = gapInfo;
    if (ms <= sharedEndRel) {
      return sharedEndRel > 0 ? (ms / sharedEndRel) * section1Width : 0;
    }
    if (ms < forkStartRel) {
      const gapFrac = (ms - sharedEndRel) / Math.max(forkStartRel - sharedEndRel, 1);
      return section1Width + gapFrac * GAP_VISUAL_PCT;
    }
    const newDuration = totalMs - forkStartRel;
    const newFrac = newDuration > 0 ? (ms - forkStartRel) / newDuration : 0;
    return section2Start + newFrac * section2Width;
  }, [gapInfo, totalMs]);

  // Filter axis ticks so none fall inside the compressed gap region (they'd overlap).
  const visibleTicks = useMemo(() => {
    if (!gapInfo) return AXIS_TICKS;
    const { sharedEndRel, forkStartRel } = gapInfo;
    return AXIS_TICKS.filter(f => {
      const ms = f * totalMs;
      return ms <= sharedEndRel || ms >= forkStartRel;
    });
  }, [gapInfo, totalMs]);

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

      {/* ── Re-explore gap separator ─────────────────────────────────────── */}
      {gapInfo && (
        <div
          title={forkLineHovered ? undefined : `re-explore v${forkNode?.version ?? ''}`}
          onMouseEnter={() => setForkLineHovered(true)}
          onMouseLeave={() => setForkLineHovered(false)}
          style={{
            position: 'absolute',
            top: 0, bottom: 0,
            // Account for the label width column — the bar track starts after LABEL_W.
            left: `calc(${LABEL_W}px + (100% - ${LABEL_W}px) * ${gapInfo.dashLinePct / 100})`,
            width: forkLineHovered ? 2 : 1,
            background: 'transparent',
            borderLeft: `${forkLineHovered ? 2 : 1}px dashed ${COLOR_TEXT_MUTED}`,
            pointerEvents: 'auto',
            cursor: 'default',
            zIndex: 10,
            transition: 'border-width 0.1s',
          }}
        >
          {forkLineHovered && (
            <div
              style={{
                position: 'absolute',
                top: 4,
                left: 6,
                background: COLOR_SURFACE_CARD,
                border: `1px solid ${COLOR_TEXT_FAINT}`,
                borderRadius: 4,
                padding: '2px 6px',
                fontSize: 11,
                color: COLOR_TEXT_SECONDARY,
                whiteSpace: 'nowrap',
                pointerEvents: 'none',
              }}
            >
              re-explore v{forkNode?.version ?? ''} · {forkNode?.node_name ?? ''}
            </div>
          )}
        </div>
      )}
    </div>
  );
}

export default NodeTimeline;

