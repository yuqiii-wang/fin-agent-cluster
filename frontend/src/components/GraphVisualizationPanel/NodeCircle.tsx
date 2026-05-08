import type { GraphNode } from "./types";
import type { NodeLayout } from "./layout";
import { LABEL_OFFSET, statusColor } from "./layout";

export interface NodeCircleProps {
  layout: NodeLayout;
  taskCount: number;
  isSelected: boolean;
  /** Render at reduced opacity; pointer events disabled (outer nodes during subgraph expansion). */
  isFaded?: boolean;
  /** This subgraph container is currently expanded — show collapse indicator. */
  isExpanded?: boolean;
  onClick: (node: GraphNode, cx: number) => void;
  onHoverChange: (node: GraphNode | null) => void;
}

export function NodeCircle({ layout, taskCount, isSelected, isFaded, isExpanded, onClick, onHoverChange }: NodeCircleProps) {
  const { node, cx, cy, r } = layout;
  const color = statusColor(node.status);
  const isRunning = node.status === "running";
  const isPending = node.status === "pending";
  const isSubgraph = node.node_type === "Subgraph";

  return (
    <g
      data-testid="graph-node"
      data-node-name={node.node_name}
      data-status={node.status}
      data-node-type={node.node_type ?? "Typical"}
      onClick={(e) => { e.stopPropagation(); onClick(node, cx); }}
      onMouseEnter={() => onHoverChange(node)}
      onMouseLeave={() => onHoverChange(null)}
      style={{
        cursor: isExpanded ? "zoom-out" : isSubgraph ? "zoom-in" : "pointer",
        opacity: isFaded ? 0.3 : 1,
        pointerEvents: isFaded ? "none" : undefined,
      }}
    >
      {isSelected && (
        <circle cx={cx} cy={cy} r={r + 5} fill="none" stroke={color} strokeWidth={2} strokeDasharray="4 3" opacity={0.7} />
      )}

      {/* Outer glow ring for subgraph nodes */}
      {isSubgraph && (
        <circle
          cx={cx}
          cy={cy}
          r={r + 10}
          fill="none"
          stroke={color}
          strokeWidth={1}
          strokeDasharray="3 4"
          opacity={0.3}
        />
      )}

      <circle
        cx={cx}
        cy={cy}
        r={r}
        fill={isSubgraph ? `${color}1a` : `${color}14`}
        stroke={color}
        strokeWidth={isSubgraph ? 2 : isRunning ? 2.5 : 1.5}
        strokeDasharray={isPending ? "5 3" : undefined}
        opacity={isPending ? 0.7 : 1}
      >
        {isRunning && (
          <animate attributeName="stroke-opacity" values="1;0.4;1" dur="1.5s" repeatCount="indefinite" />
        )}
      </circle>

      {isPending ? (
        <text x={cx} y={cy + 5} textAnchor="middle" fontSize={isSubgraph ? 16 : 13} fill={color} opacity={0.6}>—</text>
      ) : isRunning ? (
        <text x={cx} y={cy + 5} textAnchor="middle" fontSize={isSubgraph ? 22 : 18} fill={color} fontFamily="monospace">⟳</text>
      ) : node.status === "completed" ? (
        <text x={cx} y={cy + 5} textAnchor="middle" fontSize={isSubgraph ? 20 : 16} fill={color}>✓</text>
      ) : node.status === "failed" ? (
        <text x={cx} y={cy + 5} textAnchor="middle" fontSize={isSubgraph ? 20 : 16} fill={color}>✕</text>
      ) : null}

      {/* Zoom indicator for subgraph nodes */}
      {isSubgraph && !isPending && (
        <text
          x={cx + r - 12}
          y={cy - r + 16}
          textAnchor="middle"
          fontSize={11}
          fill={color}
          opacity={0.7}
          style={{ userSelect: "none" }}
        >
          {isExpanded ? "⊖" : "⊕"}
        </text>
      )}

      <text
        x={cx}
        y={cy + r + LABEL_OFFSET}
        textAnchor="middle"
        fontSize={isSubgraph ? 12 : 11}
        fontWeight={isSubgraph ? "600" : "500"}
        fill="currentColor"
        style={{ userSelect: "none" }}
      >
        {node.node_name}
      </text>

      {taskCount > 0 && (
        <>
          <circle cx={cx + r - 8} cy={cy - r + 8} r={9} fill={color} />
          <text x={cx + r - 8} y={cy - r + 12} textAnchor="middle" fontSize={9} fill="#fff" fontWeight="bold">
            {taskCount}
          </text>
        </>
      )}
    </g>
  );
}
