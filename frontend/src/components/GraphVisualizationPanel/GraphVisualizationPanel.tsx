/**
 * GraphVisualizationPanel — SVG-based DAG visualization.
 *
 * Layout algorithm:
 *   1. Assign each node a depth via BFS from roots (parent_node_execution_ids = []).
 *   2. Nodes at the same depth share a column.
 *   3. Within a column, nodes are stacked vertically and centered.
 *   4. Edges are bezier curves between parent circle center → child circle center.
 *
 * Node circles:
 *   - Stroke color by status (running=blue/animated, completed=green, failed=red, cancelled=orange)
 *   - Node name below the circle
 *   - Elapsed time inside the circle (or spinner icon when running)
 *   - Click → opens NodeTaskVisualizationPanel
 */

import { useMemo, useState, useCallback, useEffect } from "react";
import { Empty, Tag, theme, Typography } from "antd";
import { CheckCircleOutlined, LoadingOutlined } from "@ant-design/icons";
import { NodeInspectorPanel } from "./NodeInspectorPanel";
import type { GraphNode, GraphState } from "./types";

const { Text } = Typography;

// ── Layout constants ──────────────────────────────────────────────────────────
const NODE_R = 36;           // circle radius
const COL_W = 120;           // horizontal spacing between column centers
const ROW_H = 100;           // vertical spacing between node centers in same col
const PAD_X = 60;            // left/right padding
const PAD_Y = 60;            // top/bottom padding
const LABEL_OFFSET = 14;     // text below circle bottom edge

// ── Status colors ─────────────────────────────────────────────────────────────
const STATUS_COLORS: Record<string, string> = {
  pending:   "#8c8c8c",
  running:   "#1677ff",
  completed: "#52c41a",
  failed:    "#ff4d4f",
  cancelled: "#fa8c16",
  paused:    "#722ed1",
};

function statusColor(status: string): string {
  return STATUS_COLORS[status] ?? "#8c8c8c";
}

function fmtElapsed(ms: number): string {
  if (ms < 1000) return `${ms}ms`;
  return `${(ms / 1000).toFixed(1)}s`;
}

// ── Layout computation ────────────────────────────────────────────────────────

interface NodeLayout {
  node: GraphNode;
  cx: number;
  cy: number;
}

function computeLayout(nodes: GraphNode[]): { layouts: NodeLayout[]; svgW: number; svgH: number } {
  if (nodes.length === 0) return { layouts: [], svgW: 0, svgH: 0 };

  // BFS to assign depth
  const depthMap = new Map<number, number>();
  const idToNode = new Map<number, GraphNode>(nodes.map((n) => [n.node_execution_id, n]));

  // Roots first
  const roots = nodes.filter((n) => n.parent_node_execution_ids.length === 0);
  roots.forEach((n) => depthMap.set(n.node_execution_id, 0));

  const queue = [...roots];
  while (queue.length > 0) {
    const curr = queue.shift()!;
    const currDepth = depthMap.get(curr.node_execution_id) ?? 0;
    nodes
      .filter((n) => n.parent_node_execution_ids.includes(curr.node_execution_id))
      .forEach((child) => {
        const prevDepth = depthMap.get(child.node_execution_id);
        const newDepth = currDepth + 1;
        if (prevDepth === undefined || newDepth > prevDepth) {
          depthMap.set(child.node_execution_id, newDepth);
        }
        if (idToNode.has(child.node_execution_id)) queue.push(child);
      });
  }
  // Nodes without a parent that aren't roots (shouldn't happen, but guard)
  nodes.forEach((n) => {
    if (!depthMap.has(n.node_execution_id)) depthMap.set(n.node_execution_id, 0);
  });

  // Group by depth
  const byDepth = new Map<number, GraphNode[]>();
  nodes.forEach((n) => {
    const d = depthMap.get(n.node_execution_id) ?? 0;
    if (!byDepth.has(d)) byDepth.set(d, []);
    byDepth.get(d)!.push(n);
  });

  const maxDepth = Math.max(...Array.from(depthMap.values()));
  const maxColSize = Math.max(...Array.from(byDepth.values()).map((g) => g.length));

  const svgW = PAD_X * 2 + (maxDepth) * COL_W + NODE_R * 2;
  const svgH = PAD_Y * 2 + (maxColSize - 1) * ROW_H + NODE_R * 2 + LABEL_OFFSET + 14;

  const layouts: NodeLayout[] = [];
  byDepth.forEach((group, depth) => {
    const colCenterX = PAD_X + NODE_R + depth * COL_W;
    const totalH = (group.length - 1) * ROW_H;
    const startY = PAD_Y + NODE_R + (((maxColSize - 1) * ROW_H) - totalH) / 2;
    group.forEach((node, i) => {
      layouts.push({ node, cx: colCenterX, cy: startY + i * ROW_H });
    });
  });

  return { layouts, svgW, svgH };
}

// ── NodeCircle component ──────────────────────────────────────────────────────

interface NodeCircleProps {
  layout: NodeLayout;
  taskCount: number;
  isSelected: boolean;
  onClick: (node: GraphNode, cx: number) => void;
  onHoverChange: (node: GraphNode | null) => void;
}

function NodeCircle({ layout, taskCount, isSelected, onClick, onHoverChange }: NodeCircleProps) {
  const { node, cx, cy } = layout;
  const color = statusColor(node.status);
  const isRunning = node.status === "running";

  const isPending = node.status === "pending";

  return (
    <g
      data-testid="graph-node"
      data-node-name={node.node_name}
      data-status={node.status}
      onClick={() => onClick(node, cx)}
      onMouseEnter={() => onHoverChange(node)}
      onMouseLeave={() => onHoverChange(null)}
      style={{ cursor: "pointer" }}
    >
      {/* Selection ring */}
      {isSelected && (
        <circle cx={cx} cy={cy} r={NODE_R + 5} fill="none" stroke={color} strokeWidth={2} strokeDasharray="4 3" opacity={0.7} />
      )}

      {/* Main circle — dashed border for pending nodes */}
      <circle
        cx={cx}
        cy={cy}
        r={NODE_R}
        fill={`${color}14`}
        stroke={color}
        strokeWidth={isRunning ? 2.5 : 1.5}
        strokeDasharray={isPending ? "5 3" : undefined}
        opacity={isPending ? 0.7 : 1}
      >
        {isRunning && (
          <animate attributeName="stroke-opacity" values="1;0.4;1" dur="1.5s" repeatCount="indefinite" />
        )}
      </circle>

      {/* Content inside circle — spinner when running, check/X/pause when terminal, dash when pending */}
      {isPending ? (
        <text x={cx} y={cy + 5} textAnchor="middle" fontSize={13} fill={color} opacity={0.6}>—</text>
      ) : isRunning ? (
        <text x={cx} y={cy + 5} textAnchor="middle" fontSize={18} fill={color} fontFamily="monospace">⟳</text>
      ) : node.status === "completed" ? (
        <text x={cx} y={cy + 5} textAnchor="middle" fontSize={16} fill={color}>✓</text>
      ) : node.status === "failed" ? (
        <text x={cx} y={cy + 5} textAnchor="middle" fontSize={16} fill={color}>✕</text>
      ) : node.status === "paused" ? (
        <text x={cx} y={cy + 5} textAnchor="middle" fontSize={16} fill={color}>⏸</text>
      ) : null}

      {/* Node name below circle */}
      <text
        x={cx}
        y={cy + NODE_R + LABEL_OFFSET}
        textAnchor="middle"
        fontSize={11}
        fontWeight="500"
        fill="currentColor"
        style={{ userSelect: "none" }}
      >
        {node.node_name}
      </text>

      {/* Task count badge */}
      {taskCount > 0 && (
        <>
          <circle cx={cx + NODE_R - 8} cy={cy - NODE_R + 8} r={9} fill={color} />
          <text x={cx + NODE_R - 8} y={cy - NODE_R + 12} textAnchor="middle" fontSize={9} fill="#fff" fontWeight="bold">
            {taskCount}
          </text>
        </>
      )}
    </g>
  );
}

// ── Edge component ────────────────────────────────────────────────────────────

interface EdgeProps {
  fromX: number;
  fromY: number;
  toX: number;
  toY: number;
  color: string;
}

function Edge({ fromX, fromY, toX, toY, color }: EdgeProps) {
  const d = `M ${fromX} ${fromY} L ${toX} ${toY}`;
  return (
    <path
      d={d}
      stroke={color}
      strokeWidth={1.5}
      fill="none"
      markerEnd="url(#graph-arrow)"
      opacity={0.55}
    />
  );
}

// ── TimelineAxis ──────────────────────────────────────────────────────────────

function niceTickIntervalMs(totalMs: number): number {
  const raw = totalMs / 5;
  const exp = Math.floor(Math.log10(Math.max(raw, 1)));
  const mag = Math.pow(10, exp);
  const n = raw / mag;
  if (n < 1.5) return mag;
  if (n < 3.5) return 2 * mag;
  if (n < 7.5) return 5 * mag;
  return 10 * mag;
}

function fmtAxisTime(ms: number): string {
  if (ms < 1000) return `${Math.round(ms)}ms`;
  return `${(ms / 1000).toFixed(1)}s`;
}

interface TimelineAxisProps {
  nodes: GraphNode[];
  hoveredNodeId: number;
  svgW: number;
}

function TimelineAxis({ nodes, hoveredNodeId, svgW }: TimelineAxisProps) {
  const AXIS_H = 74;
  const BAR_H = 14;
  const BAR_H_HOVERED = 20;
  const BAR_Y = 8;
  const AXIS_Y = 40;
  const LABEL_Y = 56;
  const PAD = 40;

  const t0 = Math.min(...nodes.map((n) => n.started_at_ms));
  const now = Date.now();
  const tMax = Math.max(...nodes.map((n) => n.ended_at_ms ?? now));
  const totalDuration = Math.max(tMax - t0, 1);
  const usableW = Math.max(svgW - 2 * PAD, 1);

  /** Linear position on the x-axis for a given timestamp. */
  function toX(ms: number): number {
    return PAD + ((ms - t0) / totalDuration) * usableW;
  }

  const tickInterval = niceTickIntervalMs(totalDuration);
  const ticks: number[] = [];
  for (let t = 0; t <= totalDuration + tickInterval * 0.01; t += tickInterval) {
    ticks.push(t);
  }

  return (
    <svg width={svgW} height={AXIS_H} style={{ display: "block", marginTop: 2 }}>
      {nodes.map((node) => {
        const isHovered = node.node_execution_id === hoveredNodeId;
        const x1 = toX(node.started_at_ms);
        // Always use the actual ended_at_ms (server-authoritative) so sequential
        // nodes never overlap — the hovered node is emphasised by height/opacity,
        // not by artificially widening its bar with a log-scale.
        const x2 = toX(node.ended_at_ms ?? now);
        const w = Math.max(x2 - x1, 4);
        const barH = isHovered ? BAR_H_HOVERED : BAR_H;
        const barY = isHovered ? BAR_Y - 3 : BAR_Y;
        const color = isHovered ? statusColor(node.status) : "#595959";
        const opacity = isHovered ? 0.9 : 0.3;
        return (
          <rect
            key={node.node_execution_id}
            x={x1}
            y={barY}
            width={w}
            height={barH}
            fill={color}
            opacity={opacity}
            rx={3}
          />
        );
      })}
      <line x1={PAD} y1={AXIS_Y} x2={svgW - PAD} y2={AXIS_Y} stroke="#595959" strokeWidth={1} opacity={0.4} />
      {ticks.map((t) => {
        const x = PAD + (t / totalDuration) * usableW;
        return (
          <g key={t}>
            <line x1={x} y1={AXIS_Y} x2={x} y2={AXIS_Y + 5} stroke="#595959" strokeWidth={1} opacity={0.4} />
            <text x={x} y={LABEL_Y} textAnchor="middle" fontSize={10} fill="#8c8c8c">
              {fmtAxisTime(t)}
            </text>
          </g>
        );
      })}
    </svg>
  );
}

// ── Main component ────────────────────────────────────────────────────────────

interface GraphVisualizationPanelProps {
  graphState: GraphState;
  threadId?: string;
  /** Accumulated LLM token streams keyed by task_id. */
  tokenStreams?: Record<string, string>;
  /** Total token counts keyed by task_id. */
  tokenCounts?: Record<string, number>;
  /** Called when the user clicks Resume — re-opens the SSE stream. */
  onResume?: () => void;
  /** True while a control action (pause/resume/cancel) is awaiting backend ack. */
  isPendingControl?: boolean;
}

export function GraphVisualizationPanel({ graphState, threadId, tokenStreams, tokenCounts, onResume, isPendingControl }: GraphVisualizationPanelProps) {
  const { token } = theme.useToken();
  const [selectedNode, setSelectedNode] = useState<GraphNode | null>(null);
  const [selectedCx, setSelectedCx] = useState<number | undefined>(undefined);
  const [hoveredNode, setHoveredNode] = useState<GraphNode | null>(null);
  const { nodes, tasks, isDone, doneStatus } = graphState;

  // Keep selectedNode in sync with live graph state so NodeInspectorPanel
  // always receives the latest status (e.g. running → cancelled).
  useEffect(() => {
    if (!selectedNode) return;
    const latest = nodes.find((n) => n.node_execution_id === selectedNode.node_execution_id);
    if (latest && latest !== selectedNode) {
      setSelectedNode(latest);
    }
  }, [nodes, selectedNode]);

  const handleHoverChange = useCallback((node: GraphNode | null) => {
    setHoveredNode(node);
  }, []);

  const { layouts, svgW, svgH } = useMemo(() => computeLayout(nodes), [nodes]);

  const taskCountByNode = useMemo(() => {
    const map = new Map<string, number>();
    tasks.forEach((t) => {
      // Find the node_id from task.input if possible
      const nodeId = typeof t.input?.node_id === "string" ? t.input.node_id : "";
      // If we have a node_id, count by node_id. Otherwise fallback to node_name.
      const key = nodeId || t.node_name;
      map.set(key, (map.get(key) ?? 0) + 1);
    });
    return map;
  }, [tasks]);

  const layoutByExecId = useMemo(
    () => new Map(layouts.map((l) => [l.node.node_execution_id, l])),
    [layouts],
  );

  const handleNodeClick = (node: GraphNode, cx: number) => {
    if (selectedNode?.node_execution_id === node.node_execution_id) {
      setSelectedNode(null);
      setSelectedCx(undefined);
    } else {
      setSelectedNode(node);
      setSelectedCx(cx);
    }
  };

  if (nodes.length === 0) {
    return (
      <div style={{ display: "flex", alignItems: "center", justifyContent: "center", minHeight: 200 }}>
        <Empty
          image={Empty.PRESENTED_IMAGE_SIMPLE}
          description={<Text type="secondary" style={{ fontSize: 13 }}>Waiting for graph nodes…</Text>}
        />
      </div>
    );
  }

  return (
    <div style={{ position: "relative" }}>
      {/* Status bar */}
      <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 12 }}>
        {isDone ? (
          <Tag icon={<CheckCircleOutlined />} color={doneStatus === "completed" ? "success" : doneStatus === "paused" ? "purple" : "error"}>
            {doneStatus ?? "done"}
          </Tag>
        ) : (
          <Tag icon={<LoadingOutlined spin />} color="processing">Running</Tag>
        )}
        <Text type="secondary" style={{ fontSize: 12 }}>
          {nodes.length} node{nodes.length !== 1 ? "s" : ""} · {tasks.length} task{tasks.length !== 1 ? "s" : ""}
          {selectedNode ? ` · ${selectedNode.node_name} selected` : " · click a node to inspect"}
        </Text>
      </div>

      {/* SVG canvas */}
      <div style={{ overflowX: "auto" }}>
        <svg
          width={svgW}
          height={svgH}
          style={{ display: "block", color: token.colorText }}
        >          <defs>
            <marker id="graph-arrow" markerWidth="7" markerHeight="7" refX="6" refY="3.5" orient="auto">
              <path d="M0,0 L0,7 L7,3.5 z" fill={token.colorBorderSecondary} />
            </marker>
          </defs>

          {/* Edges: parent → child (multi-parent fan-in supported) */}
          {nodes.flatMap((node) =>
            node.parent_node_execution_ids.map((parentId) => {
              const from = layoutByExecId.get(parentId);
              const to = layoutByExecId.get(node.node_execution_id);
              if (!from || !to) return null;
              return (
                <Edge
                  key={`${parentId}-${node.node_execution_id}`}
                  fromX={from.cx + NODE_R}
                  fromY={from.cy}
                  toX={to.cx - NODE_R}
                  toY={to.cy}
                  color={token.colorBorderSecondary}
                />
              );
            })
          )}

          {/* Node circles */}
          {layouts.map((l) => {
            const targetNodeId = (l.node.node_id as string) || (l.node.input?.node_id as string) || "";
            const key = targetNodeId || l.node.node_name;
            return (
              <NodeCircle
                key={l.node.node_execution_id}
                layout={l}
                taskCount={taskCountByNode.get(key) ?? 0}
                isSelected={selectedNode?.node_execution_id === l.node.node_execution_id}
                onClick={handleNodeClick}
                onHoverChange={handleHoverChange}
              />
            );
          })}
        </svg>
        {/* Timeline axis — shows elapsed time ranges on hover (hidden when inspector is open) */}
        {hoveredNode && !selectedNode && nodes.some((n) => n.started_at_ms) && (
          <TimelineAxis
            nodes={nodes}
            hoveredNodeId={hoveredNode.node_execution_id}
            svgW={Math.max(svgW, 200)}
          />
        )}
      </div>

      {/* Node inspector — expands inline below the SVG */}
      {selectedNode && (
        <NodeInspectorPanel
          selectedNodeCx={selectedCx}
          node={selectedNode}
          tasks={tasks}
          threadId={threadId}
          tokenStreams={tokenStreams}
          tokenCounts={tokenCounts}
          onClose={() => { setSelectedNode(null); setSelectedCx(undefined); }}
          onResume={onResume}
          isPendingControl={isPendingControl}
        />
      )}
    </div>
  );
}

