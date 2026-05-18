import React, { useMemo, useState } from 'react';
import { STATUS_BRIGHT, STATUS_DARK } from '../../constants/statusColors';
import {
  COLOR_BORDER_STRONG, COLOR_OVERLAP_BORDER, COLOR_OVERLAP_FILL,
  COLOR_PARALLEL_ACTIVE, COLOR_PARALLEL_INACTIVE,
  COLOR_SUBGRAPH_INDICATOR_DIM, COLOR_SURFACE_BASE,
  COLOR_TEXT_ACTIVE, COLOR_TEXT_BRIGHT, COLOR_TEXT_DIM, COLOR_TEXT_FAINT, COLOR_TEXT_MUTED,
  COLOR_TICK_MAIN, COLOR_STATUS_DARK_FALLBACK,
} from '../../constants/styleColors';
import { AXIS_TICKS, BAR_H, GAP_VISUAL_PCT, LABEL_W, NARROW_PCT } from './constants';
import { buildOverlapRects, formatMs } from './utils';
import type { EffectiveSpan, GapSegment } from './utils';
import TaskGantt from './TaskGantt';
import type { NodeInfo, TaskInfo } from '../../types';

const sdark   = (s: string) => STATUS_DARK[s]   ?? COLOR_STATUS_DARK_FALLBACK;
const sbright = (s: string) => STATUS_BRIGHT[s] ?? COLOR_TEXT_MUTED;

interface Props {
  rowKey: string;
  rowNodes: NodeInfo[];
  indent: number;
  fallbackLabel: string;
  hoveredNodeId: string | null;
  setHoveredNodeId: (id: string | null) => void;
  hoveredTaskId: string | null;
  setHoveredTaskId: (id: string | null) => void;
  expandedSubgraphs: Set<string>;
  expandedTaskNodeId: string | null;
  expandedParallelRows: Set<string>;
  onToggleParallelRow: (key: string) => void;
  nodeTaskMap: Map<string, TaskInfo[]>;
  childrenMap: Map<string | null, NodeInfo[]>;
  effectiveSpans: Map<string, EffectiveSpan>;
  pct: (ms: number) => number;
  tMin: number;
  onSelectNode: (id: string) => void;
  onNodeClick: (node: NodeInfo) => void;
  /** Collapses all expanded subgraphs/tasks; only provided when something is expanded. */
  onCollapseAll?: () => void;
  /** Compressed time-gap segments to render as shaded squares over each bar track. */
  gaps?: GapSegment[];
}

/** Renders BAR_H × BAR_H shaded squares over each compressed time gap. */
const GapSquares: React.FC<{
  gaps: GapSegment[];
  pct: (ms: number) => number;
}> = ({ gaps, pct }) => {
  const [hoveredIdx, setHoveredIdx] = useState<number | null>(null);
  return (
    <>
      {gaps.map((gap, i) => {
        const midPct    = pct(gap.gapStart) + GAP_VISUAL_PCT / 2;
        const skippedMs = gap.gapEnd - gap.gapStart;
        const isHov     = hoveredIdx === i;
        return (
          <div
            key={i}
            onMouseEnter={() => setHoveredIdx(i)}
            onMouseLeave={() => setHoveredIdx(null)}
            style={{
              position: 'absolute',
              top: 0, height: BAR_H, width: BAR_H,
              left: `calc(${midPct}% - ${BAR_H / 2}px)`,
              background: `repeating-linear-gradient(
                -45deg,
                rgba(140,140,140,0.18),
                rgba(140,140,140,0.18) 3px,
                transparent 3px,
                transparent 8px
              )`,
              border: `1px solid rgba(160,160,160,${isHov ? '0.6' : '0.3'})`,
              borderRadius: 2,
              boxSizing: 'border-box',
              zIndex: 10,
              cursor: 'default',
              transition: 'border-color 0.12s',
            }}
          >
            {isHov && (
              <div
                style={{
                  position: 'absolute',
                  bottom: BAR_H + 4,
                  left: '50%',
                  transform: 'translateX(-50%)',
                  background: 'rgba(24,24,24,0.95)',
                  border: '1px solid rgba(160,160,160,0.4)',
                  borderRadius: 3,
                  padding: '3px 7px',
                  fontSize: 10,
                  color: 'rgba(210,210,210,0.95)',
                  whiteSpace: 'nowrap',
                  pointerEvents: 'none',
                  zIndex: 20,
                  lineHeight: 1.5,
                }}
              >
                {formatMs(skippedMs)} skipped
                {gap.forkVersion != null && (
                  <><br />re-explore v{gap.forkVersion}{gap.forkNodeName ? ` · ${gap.forkNodeName}` : ''}</>
                )}
              </div>
            )}
          </div>
        );
      })}
    </>
  );
};

/** Renders one horizontal track for a subset of nodes (used for both shrunken and per-lane views). */
const NodeTrack: React.FC<{
  nodes: NodeInfo[];
  hoveredNodeId: string | null;
  setHoveredNodeId: (id: string | null) => void;
  expandedSubgraphs: Set<string>;
  expandedTaskNodeId: string | null;
  nodeTaskMap: Map<string, TaskInfo[]>;
  effectiveSpans: Map<string, EffectiveSpan>;
  pct: (ms: number) => number;
  tMin: number;
  onNodeClick: (node: NodeInfo) => void;
  overlapRects?: Array<{ startMs: number; endMs: number }>;
}> = ({
  nodes, hoveredNodeId, setHoveredNodeId,
  expandedSubgraphs, expandedTaskNodeId,
  nodeTaskMap, effectiveSpans, pct, tMin, onNodeClick,
  overlapRects,
}) => (
  <div
    style={{
      width: '100%', position: 'relative', height: BAR_H,
      background: COLOR_SURFACE_BASE, borderRadius: 4, overflow: 'hidden',
    }}
  >
    {AXIS_TICKS.slice(1, -1).map(f => (
      <div key={f} style={{ position: 'absolute', left: `${f * 100}%`, top: 0, bottom: 0, width: 1, background: COLOR_TICK_MAIN }} />
    ))}

    {nodes.map(node => {
      const span      = effectiveSpans.get(node.node_id);
      const startMs   = span?.startMs ?? (node.started_at ? new Date(node.started_at).getTime() : tMin);
      const elapsedMs = span?.elapsedMs ?? Math.max(node.elapsed_ms ?? 1, 1);
      const lPct      = pct(startMs - tMin);
      const wPct      = pct(Math.max(elapsedMs, 1));
      const isHov     = hoveredNodeId === node.node_id;
      const isActive  = (node.type === 'Subgraph' && expandedSubgraphs.has(node.node_id))
                      || expandedTaskNodeId === node.node_id;
      const lit       = isHov || isActive;
      const isNarrow  = wPct < NARROW_PCT;
      const isSubgraph = node.type === 'Subgraph';
      const hasTasks  = (nodeTaskMap.get(node.node_id) ?? []).length > 0;
      const clickable = isSubgraph || hasTasks;
      const bg        = lit ? sbright(node.status) : sdark(node.status);

      return (
        <div
          key={node.node_id}
          title={`${node.node_name} · ${formatMs(elapsedMs)}`}
          style={{
            position: 'absolute', left: `${lPct}%`, width: `${wPct}%`,
            height: '100%', background: bg,
            borderRight: `1px solid ${COLOR_BORDER_STRONG}`,
            borderTop: isSubgraph ? `2px solid ${lit ? sbright(node.status) : COLOR_SUBGRAPH_INDICATOR_DIM}` : undefined,
            boxSizing: 'border-box',
            cursor: clickable ? 'pointer' : 'default',
            transition: 'background 0.15s',
            display: 'flex', alignItems: 'center', paddingLeft: 4,
            overflow: 'hidden',
          }}
          onClick={() => onNodeClick(node)}
          onMouseEnter={() => setHoveredNodeId(node.node_id)}
          onMouseLeave={() => setHoveredNodeId(null)}
        >
          {lit && !isNarrow && (
            <span style={{ color: COLOR_TEXT_BRIGHT, fontSize: 10, whiteSpace: 'nowrap', pointerEvents: 'none' }}>
              {formatMs(elapsedMs)}
            </span>
          )}
        </div>
      );
    })}

    {/* Overlap highlight overlay (shrunken view only) */}
    {overlapRects?.map((rect, i) => {
      const lPct = pct(rect.startMs - tMin);
      const wPct = pct(rect.endMs - rect.startMs);
      return (
        <div
          key={i}
          style={{
            position: 'absolute', left: `${lPct}%`, width: `${wPct}%`,
            height: '100%',
            background: COLOR_OVERLAP_FILL,
            borderLeft:  `1px solid ${COLOR_OVERLAP_BORDER}`,
            borderRight: `1px solid ${COLOR_OVERLAP_BORDER}`,
            pointerEvents: 'none',
          }}
        />
      );
    })}
  </div>
);

const BarRow: React.FC<Props> = ({
  rowKey, rowNodes, indent, fallbackLabel,
  hoveredNodeId, setHoveredNodeId,
  hoveredTaskId, setHoveredTaskId,
  expandedSubgraphs, expandedTaskNodeId,
  expandedParallelRows, onToggleParallelRow,
  nodeTaskMap, childrenMap, effectiveSpans,
  pct, tMin, onSelectNode, onNodeClick,
  onCollapseAll,
  gaps,
}) => {
  const hovNode = rowNodes.find(n => n.node_id === hoveredNodeId);

  let labelText: string;
  if (hovNode) {
    const expanded   = hovNode.type === 'Subgraph' && expandedSubgraphs.has(hovNode.node_id);
    const indicator  = hovNode.type === 'Subgraph' ? (expanded ? '▾ ' : '▸ ') : '';
    const effElapsed = effectiveSpans.get(hovNode.node_id)?.elapsedMs ?? hovNode.elapsed_ms ?? 0;
    labelText = `${indicator}${hovNode.node_name} · ${formatMs(effElapsed)}`;
  } else {
    const prefix = indent > 0 ? '└ ' : '';
    labelText = `${prefix}${fallbackLabel}`;
  }

  const expandedTaskInRow = rowNodes.find(n => n.node_id === expandedTaskNodeId);

  const overlapRects = useMemo(
    () => buildOverlapRects(rowNodes, effectiveSpans),
    [rowNodes, effectiveSpans],
  );
  const hasOverlap = overlapRects.length > 0;
  const isParallelExpanded = hasOverlap && expandedParallelRows.has(rowKey);

  const sharedProps = {
    hoveredNodeId, setHoveredNodeId,
    hoveredTaskId, setHoveredTaskId,
    expandedSubgraphs, expandedTaskNodeId,
    expandedParallelRows, onToggleParallelRow,
    nodeTaskMap, childrenMap, effectiveSpans,
    pct, tMin, onSelectNode, onNodeClick,
    gaps,
  };

  const trackSharedProps = {
    hoveredNodeId, setHoveredNodeId,
    expandedSubgraphs, expandedTaskNodeId,
    nodeTaskMap, effectiveSpans,
    pct, tMin, onNodeClick,
  };

  return (
    <>
      {isParallelExpanded ? (
        // ── Expanded parallel: header + one labeled row per node ──────────
        <>
          {/* header row — toggle button + row label */}
          <div style={{ display: 'flex', alignItems: 'center', marginBottom: 2 }}>
            <div
              style={{
                width: LABEL_W, flexShrink: 0, paddingRight: 8, textAlign: 'right',
                fontSize: 11, color: COLOR_TEXT_DIM, overflow: 'hidden',
                textOverflow: 'ellipsis', whiteSpace: 'nowrap',
              }}
            >
              <span
                title="Collapse parallel lanes"
                onClick={e => { e.stopPropagation(); onToggleParallelRow(rowKey); }}
                style={{ cursor: 'pointer', marginRight: 4, color: COLOR_PARALLEL_ACTIVE }}
              >
                ⊟
              </span>
              {indent > 0 ? `└ ${fallbackLabel}` : fallbackLabel}
            </div>
            <div style={{ flex: 1 }} />
          </div>

          {/* one row per node, with inline subgraph + task expansion */}
          {rowNodes.map(node => {
            const span      = effectiveSpans.get(node.node_id);
            const elapsedMs = span?.elapsedMs ?? Math.max(node.elapsed_ms ?? 1, 1);
            const isHov     = hoveredNodeId === node.node_id;
            const isSg      = node.type === 'Subgraph';
            const sgExp     = isSg && expandedSubgraphs.has(node.node_id);
            const indicator = isSg ? (sgExp ? '▾ ' : '▸ ') : '';
            const nodeLabel = `${indicator}${node.node_name} · ${formatMs(elapsedMs)}`;
            return (
              <React.Fragment key={node.node_id}>
                <div style={{ display: 'flex', alignItems: 'center', marginBottom: 2 }}>
                  <div
                    style={{
                      width: LABEL_W, flexShrink: 0, paddingRight: 8, paddingLeft: 12,
                      textAlign: 'right', color: isHov ? COLOR_TEXT_ACTIVE : COLOR_TEXT_MUTED, fontSize: 10,
                      overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap',
                    }}
                    title={nodeLabel}
                  >
                    {nodeLabel}
                  </div>
                  <div style={{ flex: 1, position: 'relative' }}>
                    <NodeTrack nodes={[node]} {...trackSharedProps} />
                    {gaps && gaps.length > 0 && <GapSquares gaps={gaps} pct={pct} />}
                  </div>
                </div>
                {/* inline task Gantt for leaf nodes */}
                {expandedTaskNodeId === node.node_id && (
                  <TaskGantt
                    node={node}
                    nodeTaskMap={nodeTaskMap}
                    hoveredTaskId={hoveredTaskId}
                    setHoveredTaskId={setHoveredTaskId}
                    pct={pct}
                    tMin={tMin}
                  />
                )}
                {/* inline child BarRow for subgraph nodes */}
                {isSg && sgExp && (
                  <BarRow
                    rowKey={`sg:${node.node_id}`}
                    rowNodes={childrenMap.get(node.node_id) ?? []}
                    indent={indent + 1}
                    fallbackLabel={node.node_name}
                    {...sharedProps}
                  />
                )}
              </React.Fragment>
            );
          })}
        </>
      ) : (
        // ── Shrunken: single bar row with overlap highlight ────────────────
        <div style={{ display: 'flex', alignItems: 'flex-start', marginBottom: 4 }}>
          <div
            style={{
              width: LABEL_W, flexShrink: 0, paddingRight: 8, textAlign: 'right',
              color: hovNode ? COLOR_TEXT_ACTIVE : COLOR_TEXT_FAINT, fontSize: 11,
              overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap',
              transition: 'color 0.15s', paddingTop: 4,
            }}
            title={labelText}
          >
            {hasOverlap && (
              <span
                title="Expand parallel lanes"
                onClick={e => { e.stopPropagation(); onToggleParallelRow(rowKey); }}
                style={{ cursor: 'pointer', marginRight: 4, color: COLOR_PARALLEL_INACTIVE }}
              >
                ⊞
              </span>
            )}
            {!hovNode && onCollapseAll ? (
              <span
                title="Shrink all"
                onClick={e => { e.stopPropagation(); onCollapseAll(); }}
                style={{ cursor: 'pointer' }}
              >
                {labelText}
              </span>
            ) : labelText}
          </div>
          <div style={{ flex: 1, position: 'relative' }}>
            <NodeTrack nodes={rowNodes} overlapRects={overlapRects} {...trackSharedProps} />
            {gaps && gaps.length > 0 && <GapSquares gaps={gaps} pct={pct} />}
          </div>
        </div>
      )}

      {/* ── Child bar rows for expanded subgraphs (shrunken mode only) ── */}
      {!isParallelExpanded && rowNodes
        .filter(n => n.type === 'Subgraph' && expandedSubgraphs.has(n.node_id))
        .map(n => (
          <React.Fragment key={n.node_id}>
            <BarRow
              rowKey={`sg:${n.node_id}`}
              rowNodes={childrenMap.get(n.node_id) ?? []}
              indent={indent + 1}
              fallbackLabel={n.node_name}
              {...sharedProps}
            />
          </React.Fragment>
        ))
      }

      {/* ── Task Gantt for expanded leaf (shrunken mode only) ── */}
      {!isParallelExpanded && expandedTaskInRow && (
        <TaskGantt
          node={expandedTaskInRow}
          nodeTaskMap={nodeTaskMap}
          hoveredTaskId={hoveredTaskId}
          setHoveredTaskId={setHoveredTaskId}
          pct={pct}
          tMin={tMin}
        />
      )}
    </>
  );
};

export default BarRow;
