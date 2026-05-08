/**
 * GraphVisualizationPanel — SVG-based horizontal DAG visualization.
 *
 * Outer view: all outer-graph nodes in horizontal column layout.
 *
 * Subgraph expansion: clicking a Subgraph container node zooms in-place —
 * the inner DAG expands (animated scale) centered at the container's position
 * in the same SVG.  The outer graph dims behind it.
 * Clicking any empty area of the SVG collapses back to the outer view.
 */

import { useMemo, useState, useCallback, useEffect } from "react";
import { Empty, Tag, theme, Typography } from "antd";
import { CheckCircleOutlined, LoadingOutlined } from "@ant-design/icons";
import { NodeInspectorPanel } from "./inspector";
import type { GraphNode, GraphState } from "./types";
import { computeLayout } from "./layout";
import { NodeCircle } from "./NodeCircle";
import { Edge } from "./Edge";
import { TimelineAxis } from "./TimelineAxis";
import { SubgraphExpandedView } from "./SubgraphExpandedView";
import { useOuterEdgeDefs, useInnerEdgeDefs, useInnerGraph } from "./hooks";

const { Text } = Typography;

/** Extra padding added around inner graph when computing SVG bounds. */
const EXPAND_PAD = 24;

interface GraphVisualizationPanelProps {
  graphState: GraphState;
  threadId?: string;
  tokenStreams?: Record<string, string>;
  tokenCounts?: Record<string, number>;
  onResume?: () => void;
  isPendingControl?: boolean;
}

export function GraphVisualizationPanel({
  graphState,
  threadId,
  tokenStreams,
  tokenCounts,
  onResume,
  isPendingControl,
}: GraphVisualizationPanelProps) {
  const { token } = theme.useToken();
  const [selectedNode, setSelectedNode] = useState<GraphNode | null>(null);
  const [selectedCx, setSelectedCx] = useState<number | undefined>(undefined);
  const [hoveredNode, setHoveredNode] = useState<GraphNode | null>(null);
  const [expandedSubgraph, setExpandedSubgraph] = useState<string | null>(null);

  const { nodes, tasks, isDone, doneStatus, topology } = graphState;
  const hasTopology = topology != null;

  useEffect(() => {
    if (nodes.length === 0) {
      setExpandedSubgraph(null);
      setSelectedNode(null);
      setSelectedCx(undefined);
    }
  }, [nodes.length]);

  useEffect(() => {
    if (!selectedNode) return;
    const latest = nodes.find((n) => n.node_execution_id === selectedNode.node_execution_id);
    if (latest && latest !== selectedNode) setSelectedNode(latest);
  }, [nodes, selectedNode]);

  const handleHoverChange = useCallback((node: GraphNode | null) => setHoveredNode(node), []);

  // ── Outer layout ──────────────────────────────────────────────────────────

  const visibleNodes = useMemo((): GraphNode[] => {
    if (!hasTopology) return nodes.filter((n) => !n.is_synthetic);
    return nodes.filter((n) => n.is_synthetic || !n.subgraph_parent);
  }, [nodes, hasTopology]);

  const topologyParentMap = useMemo(() => {
    if (!topology) return undefined;
    const map = new Map<string, string[]>();
    topology.outer_nodes.forEach((tn) => map.set(tn.node_name, tn.parent_node_names));
    return map;
  }, [topology]);

  const { layouts, svgW: baseSvgW, svgH: outerSvgH } = useMemo(
    () => computeLayout(visibleNodes, topologyParentMap),
    [visibleNodes, topologyParentMap],
  );

  // ── Inner graph ───────────────────────────────────────────────────────────

  const { expandedInnerData, innerPositions, innerNodeLayouts, innerSvgW, innerSvgH } =
    useInnerGraph(expandedSubgraph, topology, nodes);

  const containerLayout = useMemo(
    () => (expandedSubgraph ? layouts.find((l) => l.node.node_name === expandedSubgraph) ?? null : null),
    [expandedSubgraph, layouts],
  );

  const innerTranslateX = containerLayout
    ? Math.max(EXPAND_PAD, containerLayout.cx - innerSvgW / 2)
    : 0;
  const innerTranslateY = containerLayout
    ? Math.max(EXPAND_PAD, containerLayout.cy - innerSvgH / 2)
    : 0;

  // ── Edges ─────────────────────────────────────────────────────────────────

  const outerEdgeDefs = useOuterEdgeDefs(hasTopology, topology, layouts, visibleNodes);
  const innerEdgeDefs = useInnerEdgeDefs(expandedInnerData?.topoNodes ?? null, innerPositions);

  // ── SVG sizing ────────────────────────────────────────────────────────────

  const continuationLayouts = useMemo(() => {
    if (isDone) return [];
    const childSet = new Set(visibleNodes.flatMap((n) => n.parent_node_execution_ids));
    return layouts.filter(
      (l) => l.node.status === "running" && !l.node.is_synthetic && !childSet.has(l.node.node_execution_id),
    );
  }, [isDone, visibleNodes, layouts]);

  const svgW = useMemo(() => {
    const base = continuationLayouts.length > 0 ? baseSvgW + 50 : baseSvgW;
    if (expandedSubgraph && innerSvgW > 0)
      return Math.max(base, innerTranslateX + innerSvgW + EXPAND_PAD);
    return base;
  }, [baseSvgW, continuationLayouts.length, expandedSubgraph, innerSvgW, innerTranslateX]);

  const svgH = useMemo(() => {
    if (expandedSubgraph && innerSvgH > 0)
      return Math.max(outerSvgH, innerTranslateY + innerSvgH + EXPAND_PAD);
    return outerSvgH;
  }, [outerSvgH, expandedSubgraph, innerSvgH, innerTranslateY]);

  // ── Task count badge ──────────────────────────────────────────────────────

  const taskCountByNode = useMemo(() => {
    const map = new Map<string, number>();
    tasks.forEach((t) => {
      const key = (typeof t.input?.node_id === "string" ? t.input.node_id : "") || t.node_name;
      map.set(key, (map.get(key) ?? 0) + 1);
    });
    return map;
  }, [tasks]);

  // ── Timeline nodes ────────────────────────────────────────────────────────
  // When zoomed into a subgraph, show individual inner nodes on the timeline.
  // In the outer view, replace synthetic subgraph containers with aggregated
  // timing derived from their inner nodes (first start → last end).

  const timelineNodes = useMemo((): GraphNode[] => {
    if (expandedSubgraph) {
      return innerNodeLayouts.map((l) => l.node);
    }
    const now = Date.now();
    return visibleNodes.map((n) => {
      if (n.node_type !== "Subgraph" || !n.is_synthetic) return n;
      const innerNodes = nodes.filter((x) => x.subgraph_parent === n.node_name && x.started_at_ms > 0);
      if (innerNodes.length === 0) return n;
      const aggStart = Math.min(...innerNodes.map((x) => x.started_at_ms));
      const aggEnd = Math.max(...innerNodes.map((x) => x.ended_at_ms ?? now));
      return { ...n, started_at_ms: aggStart, ended_at_ms: aggEnd };
    });
  }, [expandedSubgraph, innerNodeLayouts, visibleNodes, nodes]);

  // ── Click handlers ────────────────────────────────────────────────────────

  const handleNodeClick = useCallback(
    (node: GraphNode, cx: number) => {
      if (node.node_type === "Subgraph") {
        setExpandedSubgraph((prev) => (prev === node.node_name ? null : node.node_name));
        setSelectedNode(null);
        setSelectedCx(undefined);
        return;
      }
      if (node.is_synthetic) return;
      if (selectedNode?.node_execution_id === node.node_execution_id) {
        setSelectedNode(null);
        setSelectedCx(undefined);
      } else {
        setSelectedNode(node);
        setSelectedCx(cx);
      }
    },
    [selectedNode],
  );

  const handleZoomOut = useCallback(() => {
    setExpandedSubgraph(null);
    setSelectedNode(null);
    setSelectedCx(undefined);
  }, []);

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
      <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 12, flexWrap: "wrap" }}>
        {isDone ? (
          <Tag icon={<CheckCircleOutlined />} color={doneStatus === "completed" ? "success" : "error"}>
            {doneStatus ?? "done"}
          </Tag>
        ) : (
          <Tag icon={<LoadingOutlined spin />} color="processing">Running</Tag>
        )}
        <Text type="secondary" style={{ fontSize: 12 }}>
          {expandedSubgraph
            ? `${expandedSubgraph} · ${innerNodeLayouts.length} inner node${innerNodeLayouts.length !== 1 ? "s" : ""}`
            : `${visibleNodes.length} node${visibleNodes.length !== 1 ? "s" : ""} · ${tasks.length} task${tasks.length !== 1 ? "s" : ""}`}
          {selectedNode ? ` · ${selectedNode.node_name} selected` : " · click a node to inspect"}
        </Text>
      </div>

      {/* SVG canvas */}
      <div style={{ overflowX: "auto" }}>
        <svg
          width={svgW}
          height={svgH}
          style={{ display: "block", color: token.colorText }}
          onClick={() => { if (expandedSubgraph) handleZoomOut(); }}
        >
          <defs>
            <marker id="graph-arrow" markerWidth="7" markerHeight="7" refX="6" refY="3.5" orient="auto">
              <path d="M0,0 L0,7 L7,3.5 z" fill={token.colorBorderSecondary} />
            </marker>
          </defs>

          {/* Outer graph — dims and becomes non-interactive when subgraph is expanded */}
          <g style={{
            opacity: expandedSubgraph ? 0.18 : 1,
            transition: "opacity 0.25s",
            pointerEvents: expandedSubgraph ? "none" : undefined,
          }}>
            {outerEdgeDefs.map((e) => (
              <Edge key={e.key} fromX={e.fromX} fromY={e.fromY} toX={e.toX} toY={e.toY} color={token.colorBorderSecondary} />
            ))}
            {layouts.map((l) => {
              const targetNodeId = (l.node.node_id as string) || (l.node.input?.node_id as string) || "";
              const key = targetNodeId || l.node.node_name;
              return (
                <NodeCircle
                  key={l.node.node_execution_id}
                  layout={l}
                  taskCount={taskCountByNode.get(key) ?? 0}
                  isSelected={selectedNode?.node_execution_id === l.node.node_execution_id}
                  isExpanded={l.node.node_name === expandedSubgraph}
                  onClick={handleNodeClick}
                  onHoverChange={handleHoverChange}
                />
              );
            })}
            {continuationLayouts.map((l) => (
              <text
                key={`more-${l.node.node_execution_id}`}
                x={l.cx + l.r + 10}
                y={l.cy + 5}
                fontSize={20}
                fill={token.colorTextSecondary}
                opacity={0.5}
                letterSpacing={3}
                style={{ userSelect: "none" }}
              >
                ...
              </text>
            ))}
          </g>

          {/* Expanded inner subgraph — centered at container, animated scale */}
          {expandedSubgraph && containerLayout && innerSvgW > 0 && (
            <SubgraphExpandedView
              expandedSubgraph={expandedSubgraph}
              innerNodeLayouts={innerNodeLayouts}
              innerEdgeDefs={innerEdgeDefs}
              innerSvgW={innerSvgW}
              innerSvgH={innerSvgH}
              containerCx={containerLayout.cx}
              containerCy={containerLayout.cy}
              selectedNodeExecutionId={selectedNode?.node_execution_id}
              taskCountByNode={taskCountByNode}
              onNodeClick={handleNodeClick}
              onHoverChange={handleHoverChange}
              onZoomOut={handleZoomOut}
            />
          )}
        </svg>

        {/* Timeline axis */}
        {hoveredNode && !selectedNode && timelineNodes.some((n) => n.started_at_ms > 0) && (
          <TimelineAxis
            nodes={timelineNodes}
            hoveredNodeId={hoveredNode.node_execution_id}
            svgW={Math.max(svgW, 200)}
          />
        )}
      </div>

      {/* Node inspector */}
      {selectedNode && !selectedNode.is_synthetic && (
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
