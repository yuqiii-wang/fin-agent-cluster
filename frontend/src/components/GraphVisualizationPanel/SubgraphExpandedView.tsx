/**
 * SubgraphExpandedView — renders inner nodes of an expanded subgraph directly
 * in the outer SVG, centered at the subgraph container node's position.
 *
 * Expand animation: inner content scales from 0 → 1 originating from the
 * container's center using a CSS transform + requestAnimationFrame trick.
 *
 * Click propagation on the root <g> is stopped so that clicks within the
 * inner graph area don't bubble to the SVG's background click handler.
 */

import { useLayoutEffect, useRef } from "react";
import { theme } from "antd";
import type { GraphNode } from "./types";
import type { EdgeDef } from "./hooks";
import { Edge } from "./Edge";
import { NodeCircle } from "./NodeCircle";

interface SubgraphExpandedViewProps {
  /** Name of the expanded subgraph — used as animation key. */
  expandedSubgraph: string;
  innerNodeLayouts: Array<{ node: GraphNode; cx: number; cy: number; r: number }>;
  innerEdgeDefs: EdgeDef[];
  innerSvgW: number;
  innerSvgH: number;
  /** Container node center X in outer SVG coordinates. */
  containerCx: number;
  /** Container node center Y in outer SVG coordinates. */
  containerCy: number;
  selectedNodeExecutionId?: number;
  taskCountByNode: Map<string, number>;
  onNodeClick: (node: GraphNode, cx: number) => void;
  onHoverChange: (node: GraphNode | null) => void;
  /** Called when the user clicks any non-node area inside the subgraph. */
  onZoomOut?: () => void;
}

const MIN_PAD = 20;

export function SubgraphExpandedView({
  expandedSubgraph,
  innerNodeLayouts,
  innerEdgeDefs,
  innerSvgW,
  innerSvgH,
  containerCx,
  containerCy,
  selectedNodeExecutionId,
  taskCountByNode,
  onNodeClick,
  onHoverChange,
  onZoomOut,
}: SubgraphExpandedViewProps) {
  const { token } = theme.useToken();
  const animRef = useRef<SVGGElement>(null);

  // Expand animation: scale 0 → 1 centered at the inner graph's visual center
  // (which maps to the container's screen position due to the translate).
  useLayoutEffect(() => {
    const el = animRef.current;
    if (!el) return;
    el.style.transformOrigin = `${innerSvgW / 2}px ${innerSvgH / 2}px`;
    el.style.transform = "scale(0)";
    el.style.opacity = "0";
    el.style.transition = "none";
    void el.getBoundingClientRect(); // flush layout so "none" transition is committed
    requestAnimationFrame(() => {
      el.style.transform = "scale(1)";
      el.style.opacity = "1";
      el.style.transition = "transform 0.35s cubic-bezier(0.34,1.56,0.64,1), opacity 0.2s";
    });
  // Re-run whenever the subgraph identity or inner dimensions change.
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [expandedSubgraph, innerSvgW, innerSvgH]);

  // Translate so the inner graph's center aligns with the container node center.
  const translateX = Math.max(MIN_PAD, containerCx - innerSvgW / 2);
  const translateY = Math.max(MIN_PAD, containerCy - innerSvgH / 2);

  return (
    <g
      transform={`translate(${translateX}, ${translateY})`}
    >
      {/* Background card — clicking any non-node area collapses the subgraph */}
      <rect
        x={0}
        y={0}
        width={innerSvgW}
        height={innerSvgH}
        rx={14}
        fill={token.colorBgElevated}
        stroke={token.colorPrimary}
        strokeWidth={1}
        strokeDasharray="6 4"
        opacity={0.92}
        style={{ cursor: "zoom-out" }}
        onClick={(e) => { e.stopPropagation(); onZoomOut?.(); }}
      />

      {/* Animated content: edges + nodes, scales from container center */}
      <g ref={animRef}>
        {innerEdgeDefs.map((e) => (
          <Edge key={e.key} fromX={e.fromX} fromY={e.fromY} toX={e.toX} toY={e.toY} color={token.colorBorderSecondary} />
        ))}
        {innerNodeLayouts.map((l) => {
          const targetNodeId = (l.node.node_id as string) || (l.node.input?.node_id as string) || "";
          const key = targetNodeId || l.node.node_name;
          return (
            <NodeCircle
              key={l.node.node_execution_id}
              layout={l}
              taskCount={taskCountByNode.get(key) ?? 0}
              isSelected={selectedNodeExecutionId === l.node.node_execution_id}
              onClick={onNodeClick}
              onHoverChange={onHoverChange}
            />
          );
        })}
      </g>
    </g>
  );
}
