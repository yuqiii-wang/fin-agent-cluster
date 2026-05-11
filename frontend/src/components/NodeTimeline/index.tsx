/**
 * NodeTimeline — hierarchical sectioned bar timeline.
 *
 * Root bar: top-level nodes (no parent_node_id) as positioned sections.
 * Subgraph nodes (type === "Subgraph") expand on click to reveal a child bar
 * row below, recursively. Leaf nodes expand to show task-level Gantt rows.
 *
 * Narrow sections (< NARROW_PCT % of track) omit the inline elapsed label;
 * it is shown instead in the left label area on hover.
 */

import React, { useCallback, useEffect, useMemo, useState } from 'react';
import type { NodeInfo, TaskInfo } from '../../types';
import { COLOR_TEXT_ACTIVE, COLOR_TEXT_FAINT } from '../../constants/styleColors';
import { buildChildrenMap, buildEffectiveSpans, buildNodeTaskMap, buildOverlapRects, formatMs } from './utils';
import { AXIS_TICKS, LABEL_W } from './constants';
import BarRow from './BarRow';

interface Props {
  nodes: NodeInfo[];
  tasks: TaskInfo[];
  selectedNodeId: string | null;
  onSelectNode: (nodeId: string) => void;
}

function NodeTimeline({ nodes, tasks, selectedNodeId, onSelectNode }: Props) {
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
  const childrenMap    = useMemo(() => buildChildrenMap(nodes), [nodes]);
  const effectiveSpans = useMemo(
    () => buildEffectiveSpans(nodes, nodeTaskMap, childrenMap),
    [nodes, nodeTaskMap, childrenMap],
  );

  // Auto-expand rows that contain overlapping parallel nodes.
  useEffect(() => {
    setExpandedParallelRows(prev => {
      let changed = false;
      const next = new Set(prev);
      // Root row
      const roots = childrenMap.get(null) ?? [];
      if (buildOverlapRects(roots, effectiveSpans).length > 0 && !next.has('root')) {
        next.add('root'); changed = true;
      }
      // Each subgraph's children row
      for (const n of nodes) {
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
  }, [childrenMap, effectiveSpans, nodes]);

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

  const pct = useCallback((ms: number) => (ms / totalMs) * 100, [totalMs]);

  const isExpanded = expandedSubgraphs.size > 0 || expandedTaskNodeId !== null || expandedParallelRows.size > 0;

  const handleCollapseAll = useCallback(() => {
    setExpandedSubgraphs(new Set());
    setExpandedTaskNodeId(null);
    setExpandedParallelRows(new Set());
  }, []);

  const handleNodeClick = useCallback((node: NodeInfo) => {
    // Always select the node for the detail panel (no deselect on re-click).
    onSelectNode(node.node_id);
    if (node.type === 'Subgraph') {
      setExpandedSubgraphs(prev => {
        const next = new Set(prev);
        next.has(node.node_id) ? next.delete(node.node_id) : next.add(node.node_id);
        return next;
      });
    } else {
      // Toggle inline task Gantt independently from detail selection.
      const hasTasks = (nodeTaskMap.get(node.node_id) ?? []).length > 0;
      if (hasTasks) {
        setExpandedTaskNodeId(prev => prev === node.node_id ? null : node.node_id);
      }
    }
  }, [nodeTaskMap, onSelectNode]);

  const roots = childrenMap.get(null) ?? [];

  return (
    <div style={{ fontFamily: 'monospace', fontSize: 12, color: COLOR_TEXT_ACTIVE, userSelect: 'none' }}>
      {/* ── Time axis — hidden when nothing is expanded (shrunken state) ── */}
      {isExpanded && (
        <div style={{ display: 'flex', marginLeft: LABEL_W, marginBottom: 4, position: 'relative', height: 16 }}>
          {AXIS_TICKS.map(f => (
            <div
              key={f}
              style={{
                position: 'absolute', left: `${f * 100}%`,
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
    </div>
  );
}

export default NodeTimeline;
